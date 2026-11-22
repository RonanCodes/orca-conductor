"""A throwaway home repo, a fake orca, and agents shaped as the real CLI and environment shape them.

- `orca agent list` gives orcaSessionId, kind, paneKey, workspace (the workspace's display name) and a title
  that may be null. orcaSessionId is never the Claude session id that names a transcript.
- A chat's processes get ORCA_AGENT_SESSION_ID and no pane key.
- A terminal agent's get ORCA_PANE_KEY (or its scrub-safe alias ORCA_AGENT_PANE) and no session id.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
HEADER = "| Coordinator | Owns | Wiki | Asleep/Awake | Session id |\n| --- | --- | --- | --- | --- |\n"
CHAT_ID, TERM_ID = "claude_chat-docs", "orca-terminal-search"
TERM_PANE = "tab-search:leaf-search"
CHAT_ENV = {"ORCA_AGENT_SESSION_ID": CHAT_ID}
TERM_ENV = {"ORCA_PANE_KEY": TERM_PANE}


def agent(kind, sid, pane, title=None, workspace="home repo", state="done"):
    return {"agent": "claude", "hostId": "local", "kind": kind, "lastAssistantMessage": None, "orcaSessionId": sid,
            "paneKey": pane, "repo": "home-repo", "state": state, "title": title, "updatedAt": 1,
            "workspace": workspace, "worktreeId": "repo::/home-repo"}


def base_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CONDUCTOR_", "ORCA_"))}
    env.update(extra)
    return env


class HomeCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.top = Path(tmp.name).resolve()
        self.home = self.top / "home repo"  # a space, as real paths have
        (self.home / "conductor").mkdir(parents=True)
        self.state = self.top / "fake.json"
        self.agents = [agent("chat", CHAT_ID, "chat-tab-docs:leaf-docs", "🎖️ Docs"),
                       agent("terminal", TERM_ID, TERM_PANE, "🎖️ Search")]
        self.set_orca(agents=self.agents, comment="", calls=[],
                      terminals=[{"tabId": "tab-search", "leafId": "leaf-search", "handle": "term_search"}])
        self.chart = self.home / "conductor" / "org-chart.md"
        self.chart.write_text(
            "# Org chart\n\n" + HEADER
            + f"| 🎖️ Docs | Handbook | `conductor/wiki/docs/` | 🟢 awake | `{CHAT_ID}` |\n"
            + f"| 🎖️ Search | Ranking | `conductor/wiki/search/` | 🟢 awake | `{TERM_ID}` |\n")
        for slug in ("docs", "search"):
            wiki = self.home / "conductor" / "wiki" / slug
            wiki.mkdir(parents=True)
            (wiki / "index.md").write_text(f"# {slug}\n")
            (wiki / "now.md").write_text(f"# {slug}: now\n\n_Updated earlier_\n\nA real summary.\n")
            (wiki / "log.md").write_text(f"# {slug}: log\n")
        self.env = base_env(CONDUCTOR_HOME=str(self.home), CONDUCTOR_STATE_DIR=str(self.top / "state"),
                            CONDUCTOR_ORCA=str(ROOT / "tests" / "fake_orca.py"), FAKE_ORCA_STATE=str(self.state),
                            CLAUDE_PLUGIN_ROOT=str(ROOT))

    def set_orca(self, **values):
        state = json.loads(self.state.read_text()) if self.state.exists() else {}
        state.update(values)
        self.state.write_text(json.dumps(state))

    def orca(self):
        return json.loads(self.state.read_text())

    def calls(self, words):
        return [c for c in self.orca()["calls"] if " ".join(c["args"][:2]) == words]

    def run_script(self, name, *args, env=None, stdin="", cwd=None):
        return subprocess.run([str(ROOT / "scripts" / name), *args], input=stdin, capture_output=True, text=True,
                              env={**self.env, **(env or {})}, cwd=cwd)

    def fire(self, event, payload, env=None):
        """Runs every command hooks.json registers for an event, as Claude Code would."""
        groups = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"][event]
        out = []
        for group in groups:
            if group.get("matcher") not in (None, payload.get("tool_name"), payload.get("source")):
                continue
            for hook in group["hooks"]:
                done = subprocess.run(hook["command"], shell=True, input=json.dumps(payload), capture_output=True,
                                      text=True, env={**self.env, **(env or {})}, timeout=hook["timeout"])
                out.append(done.stdout)
        return "".join(out)

    def asks(self, env):
        """True when this agent's AskUserQuestion goes through."""
        payload = {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion", "session_id": "claude-session"}
        return '"deny"' not in self.fire("PreToolUse", payload, env)
