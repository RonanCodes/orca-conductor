"""coordinator_sleep: put a long-lived coordinator chat to sleep and wake it again, without ever deleting it.

A coordinator (a chief of staff over one initiative) is never closed, removed or archived. When it is idle it
sleeps: a marker goes on its workspace comment and its row in the org chart table says asleep. When work for
the initiative comes back it is woken and handed the context, instead of a new coordinator being started.

Plain functions with plain inputs and outputs (strings in, strings out), stdlib only, no I/O except the two
native seams at the bottom. A CLI or an Orca plugin wraps them; it owns reading and writing the files and
calling Orca. This is the only sleep design: the `coordinator` script wraps it, and the Orca plugin calls that
script. Sources of truth:

- The org chart is a Markdown table whose header has `Coordinator`, `Owns` and `Session id` columns, optionally
  `Wiki` and `Asleep/Awake`. The session id is the first backticked token of the `Session id` cell.
- The workspace comment can hold one `💤 <name> asleep since <YYYY-MM-DD>: <note>` segment per sleeping
  coordinator (several coordinators may share one workspace), after any other text, which is kept as is.
"""
import re

ASLEEP = "\U0001F4A4"                 # 💤
AWAKE_CELL = "\U0001F7E2 awake"       # 🟢 awake
NAME_HEADER = "Coordinator"
STATE_HEADER = "Asleep/Awake"
SESSION_HEADER = "Session id"

# Subcommand words that would end a coordinator. No command may use them on a coordinator, and an Orca call
# whose command words include one is refused before it runs (sleep and wake must never close or remove).
FORBIDDEN_WORDS = frozenset({"delete", "archive", "rm", "remove", "close", "kill", "stop", "destroy", "retire"})

_SEGMENT = re.compile(ASLEEP + r" (?P<name>.+?) asleep since (?P<date>\d{4}-\d{2}-\d{2}): (?P<note>.*?)(?= " +
                      ASLEEP + r" |$)", re.M)


def clean_note(note):
    """One line, no 💤 (it starts a segment) and no table pipes, so the note survives both homes."""
    note = re.sub(r"\s+", " ", (note or "").replace(ASLEEP, "")).strip()
    return note.replace("|", "/")


# ---------- the workspace comment ----------

def comment_marker(name, date, note):
    return f"{ASLEEP} {name} asleep since {date}: {clean_note(note)}"


def asleep_in_comment(comment):
    """{name: (date, note)} for every sleep segment in a workspace comment."""
    return {m.group("name"): (m.group("date"), m.group("note").strip()) for m in _SEGMENT.finditer(comment or "")}


def add_marker(comment, name, date, note):
    """The comment with this coordinator's sleep segment appended. Idempotent: already there, unchanged."""
    comment = comment or ""
    if name in asleep_in_comment(comment):
        return comment
    return (comment.rstrip() + " " if comment.strip() else "") + comment_marker(name, date, note)


def remove_marker(comment, name):
    """The comment without this coordinator's sleep segment; every other word is kept. Idempotent."""
    comment = comment or ""
    for m in _SEGMENT.finditer(comment):
        if m.group("name") == name:
            return re.sub(r"  +", " ", (comment[:m.start()] + comment[m.end():])).strip()
    return comment


# ---------- the org chart table ----------

def _cells(line):
    return [c.strip() for c in line.strip()[2:-2].split(" | ")]


def _is_row(line):
    s = line.strip()
    return s.startswith("| ") and s.endswith(" |")


def table_rows(text):
    """[{name, owns, wiki, state, session, line}] from the org chart table (the one whose header has Coordinator
    and Session id). `state` is the Asleep/Awake cell, or None when the table has no such column."""
    out, header = [], None
    for line in text.splitlines(keepends=True):
        if not _is_row(line):
            header = None
            continue
        cells = _cells(line)
        if header is None:
            header = cells if (NAME_HEADER in cells and SESSION_HEADER in cells) else []
            continue
        if not header or set(line.strip()) <= set("|- "):
            continue
        row = dict(zip(header, cells))
        m = re.match(r"`([^`]+)`", row.get(SESSION_HEADER, ""))
        if not m:
            continue
        out.append({"name": row.get(NAME_HEADER, ""), "owns": row.get("Owns", ""), "wiki": row.get("Wiki", ""),
                    "state": row.get(STATE_HEADER), "session": m.group(1), "line": line,
                    "state_index": header.index(STATE_HEADER) if STATE_HEADER in header else None})
    return out


def is_asleep_cell(cell):
    return bool(cell) and cell.startswith(ASLEEP)


def asleep_cell(date, note):
    note = clean_note(note)
    return f"{ASLEEP} asleep since {date}" + (f": {note}" if note else "")


def asleep_sessions(text):
    """{session id: state cell} for every sleeping coordinator in the org chart."""
    return {r["session"]: r["state"] for r in table_rows(text) if is_asleep_cell(r["state"])}


def add_state_column(text):
    """The org chart with an Asleep/Awake column before Session id (every row awake). Unchanged when the
    column is already there. Only the table's own lines change."""
    lines = text.splitlines(keepends=True)
    out, idx = [], None
    for line in lines:
        if not _is_row(line):
            idx = None
            out.append(line)
            continue
        cells = _cells(line)
        nl = "\n" if line.endswith("\n") else ""
        if idx is None:
            if NAME_HEADER in cells and SESSION_HEADER in cells and STATE_HEADER not in cells:
                idx = cells.index(SESSION_HEADER)
                cells.insert(idx, STATE_HEADER)
            else:
                idx = -1  # another table, or already migrated
            out.append("| " + " | ".join(cells) + " |" + nl if idx >= 0 else line)
            continue
        if idx < 0 or len(cells) <= idx:
            out.append(line)
            continue
        cells.insert(idx, "---" if set(line.strip()) <= set("|- ") else AWAKE_CELL)
        out.append("| " + " | ".join(cells) + " |" + nl)
    return "".join(out)


def set_state(text, session, cell):
    """The org chart with this session's Asleep/Awake cell set. Raises KeyError when the row is missing and
    ValueError when the table has no such column; only that one row changes."""
    for r in table_rows(text):
        if r["session"] != session:
            continue
        if r["state"] is None:
            raise ValueError(f"the org chart has no {STATE_HEADER} column (add_state_column)")
        cells = _cells(r["line"])
        cells[r["state_index"]] = cell
        nl = "\n" if r["line"].endswith("\n") else ""
        new = "| " + " | ".join(cells) + " |" + nl
        assert text.count(r["line"]) == 1, "the row appears more than once"
        return text.replace(r["line"], new, 1)
    raise KeyError(session)


# ---------- matching a new topic to a sleeping coordinator ----------

STOP_WORDS = frozenset("""a an and the of for to in on at by with from or is are be it its this that our we
new coordinator coordinators chief staff conductor agent agents tab was until since asleep awake idle work initiative
see handover nov dec jan feb mar apr may jun jul aug sep oct owns why notes sleeps because wiki""".split())


def topic_tokens(text):
    """Lower-case words of three or more letters or digits, without stop words, markers or ids."""
    words = re.findall(r"[0-9a-zA-ZÀ-ɏ]+", (text or "").lower())
    return {w for w in words if len(w) >= 3 and w not in STOP_WORDS and not re.fullmatch(r"[0-9a-f]{8,}|20\d\d", w)}


def match_asleep(topic, rows):
    """[(row, shared tokens)] for sleeping rows whose name, owns or sleep note shares a word with the topic,
    best first. A plain token match on purpose: a false hit costs one extra `wake`, a miss costs a duplicate."""
    want = topic_tokens(topic)
    hits = []
    for r in rows:
        if not is_asleep_cell(r.get("state")):
            continue
        shared = want & topic_tokens(" ".join((r.get("name", ""), r.get("owns", ""), r.get("state", ""))))
        if shared:
            hits.append((r, sorted(shared)))
    return sorted(hits, key=lambda h: -len(h[1]))


# ---------- guards ----------

def command_words(args):
    """The subcommand words of a CLI call: the arguments before the first option."""
    words = []
    for x in args:
        if str(x).startswith("-"):
            break
        words.append(str(x).lower())
    return words


def forbidden(args):
    """The forbidden word in this call's subcommand words (`worker-stop` counts as `stop`), or None."""
    for w in command_words(args):
        for part in re.split(r"[-_.]", w):
            if part in FORBIDDEN_WORDS:
                return part
    return None


# ---------- native seams ----------
# Orca has workspace Sleep in its sidebar only: no CLI or API call sleeps or wakes one chat, and Sleep acts on
# a whole workspace, which several coordinators may share (often the home repo's checkout). So these are no-ops
# today and the marker plus the org chart cell are the record. When Orca ships it (https://github.com/stablyai/orca/issues/46875), call it
# here and return True; nothing else changes.

def native_sleep(worktree):
    """Sleep this workspace natively. Returns True when Orca did it, False when it cannot (today)."""
    # TODO(https://github.com/stablyai/orca/issues/46875): call Orca's sleep once it has a CLI or API.
    return False


def native_wake(worktree):
    """Wake this workspace natively. Returns True when Orca did it, False when it cannot (today)."""
    # TODO(https://github.com/stablyai/orca/issues/46875): call Orca's wake once it has a CLI or API.
    return False
