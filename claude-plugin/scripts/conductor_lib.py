"""Shared logic for the conductor scripts and hooks. Python 3 standard library only.

The home repo holds everything that must outlive a chat:

    <home>/conductor/standards.md     numbered standing rules, newest first
    <home>/conductor/org-chart.md     every coordinator, awake or asleep, with its wiki and note
    <home>/conductor/wiki/<slug>/     one dated wiki per coordinator: index.md, now.md, log.md

<home> is CONDUCTOR_HOME, else the git top level of the current folder when it has a `conductor/` folder
(so a worker in an app repo never writes a second home there by accident).
"""
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import coordinator_sleep as sleeping

ROLES = ("conductor", "coordinator", "worker")
DEFAULT_MARKERS = {"conductor": "🎩", "coordinator": "🎖️", "worker": "🤖"}
DEFAULT_ASK_ROLES = ("conductor", "coordinator")
ORG_HEADER = "| Coordinator | Owns | Wiki | Asleep/Awake | Session id |"
ORG_RULE = "| --- | --- | --- | --- | --- |"
ORCA_ALLOWED = {("agent", "list"), ("terminal", "list"), ("worktree", "show"), ("worktree", "set"),
                ("orchestration", "send")}
ENTRY_RE = re.compile(r"^### S-(\d+) [•·] (.+?) [•·] (.+)$")
ENTRIES_HEADING = "## Entries"


class ConductorError(Exception):
    """A problem the person can fix; scripts print it and exit 1."""


# Home repo ------------------------------------------------------------------------------------

def home_repo(cwd=None):
    env = os.environ.get("CONDUCTOR_HOME", "").strip()
    if env:
        return Path(env).expanduser()
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True,
                             text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        out = None
    if out and out.returncode == 0 and out.stdout.strip():
        top = Path(out.stdout.strip())
        if (top / "conductor").is_dir():
            return top
    raise ConductorError("No home repo: set CONDUCTOR_HOME, or run this inside a home repo that has a conductor/ folder.")


def standards_file(home=None):
    env = os.environ.get("CONDUCTOR_STANDARDS_FILE", "").strip()
    if env:
        return Path(env).expanduser()
    return (home or home_repo()) / "conductor" / "standards.md"


def org_chart_file(home=None):
    env = os.environ.get("CONDUCTOR_ORG_CHART", "").strip()
    if env:
        return Path(env).expanduser()
    return (home or home_repo()) / "conductor" / "org-chart.md"


def now_text():
    """'YYYY-MM-DD HH:MM', or CONDUCTOR_NOW for tests."""
    return os.environ.get("CONDUCTOR_NOW") or dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def write_atomic(path, text):
    """Write through a temp file and a rename, so a reader never sees half a file."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# Orca -----------------------------------------------------------------------------------------

def orca_call(args, stdin=None, timeout=20):
    """One `orca` call. Only the few commands in ORCA_ALLOWED run, and none that would end a chat."""
    bad = sleeping.forbidden(args)
    words = tuple(sleeping.command_words(args))
    if bad or words not in ORCA_ALLOWED:
        raise ConductorError(f"refused `orca {' '.join(words)}`: these scripts never delete, close, kill or stop, "
                             "and run only agent list, terminal list, worktree show, worktree set and orchestration send")
    exe = os.environ.get("CONDUCTOR_ORCA") or "orca"
    try:
        return subprocess.run([exe, *args], input=stdin if stdin is not None else "", capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ConductorError(f"the orca CLI did not run ({exe}): {e}") from e


def orca_json(args, timeout=20):
    out = orca_call(args, timeout=timeout)
    if out.returncode != 0:
        raise ConductorError(f"orca {' '.join(sleeping.command_words(args))} failed: "
                             f"{(out.stderr or out.stdout).strip()[:200]}")
    try:
        data = json.loads(out.stdout)
        return data["result"]
    except (ValueError, KeyError, TypeError) as e:
        raise ConductorError("the orca CLI answered in a shape these scripts do not know") from e


def orca_agents(timeout=20):
    return orca_json(["agent", "list", "--json"], timeout).get("agents") or []


def mail_address(session, agents):
    """A chat takes mail at orca_session_id:<id>. Orca refuses that for a terminal agent, which takes it on
    its terminal handle: the one whose tabId:leafId is the agent's paneKey."""
    agent = next((a for a in agents if a.get("orcaSessionId") == session), None)
    if not agent or agent.get("kind") != "terminal":
        return f"orca_session_id:{session}"
    for term in orca_json(["terminal", "list", "--limit", "1000", "--json"]).get("terminals") or []:
        if f"{term.get('tabId')}:{term.get('leafId')}" == agent.get("paneKey") and term.get("handle"):
            return term["handle"]
    raise ConductorError("it is a terminal agent with no live terminal: reopen its workspace first")


def send_mail(session, subject, body, to=None):
    """Mail a coordinator. None when Orca took it, else why it was not sent. Taken is not the same as read."""
    try:
        to = to or mail_address(session, orca_agents())
        out = orca_call(["orchestration", "send", "--to", to, "--subject", subject, "--body-file", "-",
                         "--type", "status", "--json"], stdin=body)
    except ConductorError as e:
        return str(e)
    return None if out.returncode == 0 else (out.stderr or out.stdout).strip()[:300]


# Roles ----------------------------------------------------------------------------------------

def _bare(text):
    return text.replace("︎", "").replace("️", "")


def markers_from_env():
    """CONDUCTOR_MARKERS='conductor=🎩,coordinator=🎖️,worker=🤖' overrides the defaults."""
    markers = dict(DEFAULT_MARKERS)
    for part in os.environ.get("CONDUCTOR_MARKERS", "").split(","):
        if "=" in part:
            role, marker = (p.strip() for p in part.split("=", 1))
            if role in ROLES and marker:
                markers[role] = marker
    return markers


def role_from_title(title, markers=None):
    """The role a title's leading marker names, or None. The conductor is checked first."""
    if not title:
        return None
    markers = markers or DEFAULT_MARKERS
    text = _bare(title).lstrip()
    for role in ROLES:
        marker = _bare(markers.get(role, ""))
        if marker and text.startswith(marker):
            return role
    return None


def ask_roles_from_env():
    raw = os.environ.get("CONDUCTOR_ASK_ROLES", "").strip()
    if not raw:
        return DEFAULT_ASK_ROLES
    return tuple(word for word in re.split(r"[\s,]+", raw.lower()) if word in ROLES)


def ask_deny_reason(role, ask_roles=DEFAULT_ASK_ROLES):
    """The deny reason for AskUserQuestion, or None to allow. An unknown role is allowed."""
    if role is None or role in ask_roles:
        return None
    allowed = " or ".join(ask_roles) or "no role"
    return (f"This agent's role is {role}, and only the {allowed} may ask the person. "
            'Send the question to your coordinator instead: orca orchestration ask --question "<question>" '
            "(then end your turn; Orca wakes you with the answer). Outside a Run, use orca orchestration send to it.")


# Standards ------------------------------------------------------------------------------------

def parse_entries(text):
    """Entries in file order (newest first): dicts with num, id, when, title, body."""
    entries, current = [], None
    for line in text.splitlines():
        m = ENTRY_RE.match(line)
        if m:
            current = {"num": int(m.group(1)), "id": f"S-{int(m.group(1)):03d}", "when": m.group(2),
                       "title": m.group(3), "body": []}
            entries.append(current)
        elif line.startswith("## ") and current is not None:
            current = None
        elif current is not None:
            current["body"].append(line)
    for e in entries:
        e["body"] = "\n".join(e["body"]).strip()
    return entries


def parse_id(text):
    m = re.fullmatch(r"(?:S-)?0*(\d+)", text.strip(), re.I)
    if not m:
        raise ConductorError(f"{text!r} is not an entry id like S-012 or 12")
    return int(m.group(1))


def new_standards_file():
    return ("# Standards\n\nStanding rules for every agent, newest first. Add one with `standards add`; the hook\n"
            "shows each new entry once to every running session.\n\n" + ENTRIES_HEADING + "\n")


def add_entry(text, body, title=None, source=None, when=None):
    """The file text with a new entry at the top of Entries, and the new entry's id."""
    if ENTRIES_HEADING not in text:
        text = text.rstrip() + ("\n\n" if text.strip() else "") + ENTRIES_HEADING + "\n"
    body = re.sub(r"(?m)^#", " #", body.strip())  # a line starting with # would read as a heading or an entry
    if not body:
        raise ConductorError("A standard needs text.")
    top = max((e["num"] for e in parse_entries(text)), default=0)
    num = top + 1
    title = re.sub(r"\s+", " ", title or re.split(r"(?<=[.!?])\s", body, maxsplit=1)[0]).strip().rstrip(".")[:120]
    block = f"### S-{num:03d} • {when or now_text()} • {title}\n{body}\n"
    if source:
        block += f"Source: {source}\n"
    head, rest = text.split(ENTRIES_HEADING, 1)
    rest = rest.lstrip("\n")
    return f"{head}{ENTRIES_HEADING}\n\n{block}" + (f"\n{rest}" if rest else ""), f"S-{num:03d}"


def entries_since(entries, last):
    """Entries newer than `last`, oldest first, so they read in the order they were made."""
    return sorted((e for e in entries if e["num"] > last), key=lambda e: e["num"])


def format_entries(entries, cap=1500):
    out, used = [], 0
    for e in entries:
        piece = f"{e['id']} • {e['title']}\n{e['body']}".strip()
        if used + len(piece) > cap and out:
            shown = entries[len(out) - 1]["id"]
            out.append(f"(and {len(entries) - len(out)} more: run `standards since {shown}`)")
            break
        if len(piece) > cap:
            piece = piece[:cap] + f"... (cut: run `standards show {e['id']}`)"
        out.append(piece)
        used += len(piece)
    return "\n\n".join(out)


def once_per_session(state_path, entries, source_mtime=None):
    """The entries this session has not been shown, and records them as shown.

    A new session (no state file, or a corrupt one) is marked as having seen everything up to now
    and gets nothing: its instruction files cover the past.
    """
    top = max((e["num"] for e in entries), default=0)
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(state_path), os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)  # parallel tool calls run this hook at the same moment
        try:
            last = int(json.loads(fh.read())["last_id"])
        except (ValueError, KeyError, TypeError):
            last = None
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({"last_id": max(top, last or 0)}))
        fh.flush()
        if source_mtime is not None:
            # The state file's time is the standards file's, so the hook's `-nt` fast path holds until it changes.
            os.utime(str(state_path), (source_mtime, source_mtime))
    if last is None:
        return []
    return entries_since(entries, last)


# Org chart ------------------------------------------------------------------------------------

def org_rows(home):
    path = org_chart_file(home)
    return sleeping.table_rows(path.read_text(encoding="utf-8")) if path.exists() else []


def display_name(name):
    """'App repo A' from '🎖️ 📦 App repo A • keywords': no leading markers, no keyword tail."""
    words = re.split(r" [•·] ", name.strip(), maxsplit=1)[0].split(" ")
    while words and not any(c.isalnum() for c in words[0]):
        words = words[1:]
    return " ".join(words).strip() or name.strip()


def row_role(row):
    role = role_from_title(row["name"], markers_from_env())
    return "conductor" if role == "conductor" else "coordinator"


def wiki_folder(home, row):
    """The folder the Wiki cell names: a Markdown link (from the org chart's folder), a backticked path (from
    the home repo) or a bare slug. None when empty or outside the home repo."""
    cell = (row.get("wiki") or "").strip()
    link = re.search(r"\]\(([^)]+)\)", cell)
    ticked = re.search(r"`([^`]+)`", cell)
    if link:
        path = org_chart_file(home).parent / link.group(1)
    elif ticked:
        path = home / ticked.group(1)
    elif re.fullmatch(r"[^\W_][\w-]*", cell):
        path = wiki_dir(home, cell)
    else:
        return None
    path = path.resolve()
    if path.suffix:
        path = path.parent
    return path if Path(home).resolve() in path.parents else None


def wiki_of(home, row):
    path = wiki_folder(home, row)
    if path is None:
        raise ConductorError(f"{display_name(row['name'])} has no usable Wiki cell inside the home repo.")
    return path


def find_coordinator(rows, query=None, session=None):
    """One row by a name word, whole name, wiki slug or session id. An explicit query beats the session.
    None or several raise, so a typo never sleeps, wakes or writes to the wrong coordinator."""
    if query:
        q = query.replace("orca_session_id:", "").strip().lower()
        if not q:
            raise ConductorError("Which coordinator? The name is empty.")
        def slug(row):
            parts = re.findall(r"[\w-]+", re.sub(r"/(?:index|now)\.md", "", row.get("wiki") or ""))
            return parts[-1].lower() if parts else ""
        exact = [r for r in rows if q in (r["name"].lower(), display_name(r["name"]).lower(), r["session"].lower(), slug(r))]
        hits = exact or [r for r in rows if q in display_name(r["name"]).lower()]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ConductorError(f"{query!r} matches {len(hits)} coordinators: " + ", ".join(r["name"] for r in hits))
        raise ConductorError(f"{query!r} matches no coordinator in the org chart.")
    if session:
        hits = [r for r in rows if r["session"] == session]
        if len(hits) == 1:
            return hits[0]
    raise ConductorError("Which coordinator? Pass --coordinator <wiki slug or name>, set CONDUCTOR_COORDINATOR, "
                         "or add this session's id to the org chart.")


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", _bare(text).lower()).strip("-")
    return slug or "coordinator"


# Wiki -----------------------------------------------------------------------------------------

KINDS = ("decision", "finding", "problem", "preference")
NOW_STUB = "Nothing yet."
NOW_FRESH_SECONDS = 3600


def wiki_dir(home, slug):
    return home / "conductor" / "wiki" / slug


def ensure_wiki(path, title):
    path.mkdir(parents=True, exist_ok=True)
    stubs = {
        "index.md": f"# {title}\n\nWhat this coordinator owns, and links to its topic pages.\n\n- [now](now.md): where things stand\n- [log](log.md): dated decisions and findings\n",
        "now.md": f"# {title}: now\n\n_Updated {now_text()}_\n\n{NOW_STUB}\n",
        "log.md": f"# {title}: log\n\nDated decisions, findings, problems and preferences, oldest first.\n",
    }
    for name, body in stubs.items():
        if not (path / name).exists():
            (path / name).write_text(body, encoding="utf-8")


def now_fresh(folder, agent, dry_run=False):
    """(ok, message). now.md must hold a real summary. Written in the last hour, it passes. An older one is
    stamped only when Orca shows the coordinator idle; a working or unknown one must write it itself first."""
    if folder is None:
        return False, "it has no Wiki folder in the org chart, so its now.md cannot be checked"
    path = folder / "now.md"
    if not path.is_file():
        return False, f"{path} does not exist; the coordinator writes it first (`wiki now --set -`)"
    text = path.read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.startswith(("# ", "_Updated "))).strip()
    if body in ("", NOW_STUB):
        return False, f"{path} has no summary yet; the coordinator writes it first (`wiki now --set -`)"
    age = time.time() - path.stat().st_mtime
    if age <= NOW_FRESH_SECONDS:
        return True, f"now.md updated {age / 60:.0f} min ago"
    state = (agent or {}).get("state")
    if state not in ("done", "idle"):
        return False, (f"now.md is {age / 3600:.1f} h old and the coordinator is {state or 'not listed by Orca'}; "
                       "ask it to rewrite now.md (`wiki now --set -`), then sleep it")
    if dry_run:
        return True, f"now.md is {age / 3600:.1f} h old; would stamp it (coordinator idle)"
    stamp = f"_Updated {now_text()}_"
    if re.search(r"(?m)^_Updated .*_$", text):
        text = re.sub(r"(?m)^_Updated .*_$", stamp, text, count=1)
    else:
        text = f"{text.rstrip()}\n\n{stamp}\n"
    write_atomic(path, text)
    return True, f"now.md was {age / 3600:.1f} h old; stamped it (coordinator idle)"


def log_line(text, kind, source=None, frm=None, when=None):
    if kind not in KINDS:
        raise ConductorError(f"--kind must be one of {', '.join(KINDS)}")
    claim = re.sub(r"\s+", " ", text).strip()
    if not claim:
        raise ConductorError("A log entry needs text.")
    when = when or now_text()
    extra = "".join([f" (from {frm})" if frm else "", f" [source]({source})" if source else ""])
    return when[:10], f"- {when[11:]} • {kind} • {claim}{extra}"


def append_log(log_text, day, line):
    """Adds the line under a `## <day>` heading, starting a new heading for a new day."""
    text = log_text.rstrip("\n")
    headings = re.findall(r"^## (\d{4}-\d{2}-\d{2})$", text, re.M)
    if not headings or headings[-1] != day:
        text += f"\n\n## {day}\n"
    return text + "\n" + line + "\n"


# Compaction -----------------------------------------------------------------------------------

def context_tokens(transcript_path):
    """Context size of a Claude Code session: input + cache read + cache creation tokens of the last
    main-chain assistant turn in its transcript, or what a later compaction left. None when none is found."""
    last = None
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            for raw in fh:
                if '"usage"' not in raw and '"compact_boundary"' not in raw:
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if row.get("type") == "system" and row.get("subtype") == "compact_boundary":
                    last = (row.get("compactMetadata") or {}).get("postTokens")
                    continue
                if row.get("isSidechain") or row.get("type") != "assistant":
                    continue
                usage = (row.get("message") or {}).get("usage") or {}
                total = sum(int(usage.get(k) or 0) for k in
                            ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                if total:
                    last = total
    except OSError:
        return None
    return last


def compact_candidates(rows, agents, tokens_for, threshold=300_000, idle_seconds=120, now_ms=None):
    """Which awake coordinators (and the conductor) to compact: over the threshold and idle.

    rows: org chart rows; agents: `orca agent list` rows; tokens_for(session) -> int or None.
    Returns (eligible, report) where report has one dict per row with the reason.
    """
    now_ms = now_ms if now_ms is not None else time.time() * 1000
    by_session = {a.get("orcaSessionId"): a for a in agents}
    eligible, report = [], []
    for r in rows:
        entry = {"name": r["name"], "session": r["session"], "tokens": None, "state": None, "why": ""}
        report.append(entry)
        if sleeping.is_asleep_cell(r["state"]):
            entry["why"] = "asleep"
            continue
        agent = by_session.get(r["session"])
        if not agent:
            entry["why"] = "not running in Orca"
            continue
        entry["state"] = agent.get("state")
        if agent.get("kind") == "chat":
            entry["why"] = "native chat: Orca does not expose its transcript"
            continue
        tokens = tokens_for(r["session"])
        entry["tokens"] = tokens
        if tokens is None:
            entry["why"] = "no transcript found"
        elif tokens <= threshold:
            entry["why"] = f"under {threshold:,} tokens"
        elif agent.get("state") != "done":
            entry["why"] = f"busy ({agent.get('state')})"
        elif now_ms - float(now_ms if agent.get("updatedAt") is None else agent["updatedAt"]) < idle_seconds * 1000:
            entry["why"] = f"finished less than {idle_seconds} s ago"
        else:
            entry["why"] = "due"
            eligible.append({**r, "agent": agent, "tokens": tokens})
    return eligible, report
