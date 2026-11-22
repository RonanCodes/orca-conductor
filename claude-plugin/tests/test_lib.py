"""Unit tests for the pure logic in scripts/conductor_lib.py and hooks/ask_gate.py.

Run: python3 -I -m unittest discover -s claude-plugin/tests
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
for key in [k for k in os.environ if k.startswith("ORCA_")]:
    del os.environ[key]  # the agent running the tests is not the agent under test
os.environ["CONDUCTOR_ORCA"] = str(ROOT / "tests" / "no-orca-in-tests")  # no test may reach a live Orca
sys.path.insert(0, str(ROOT / "scripts"))
import conductor_lib as lib  # noqa: E402

spec = importlib.util.spec_from_file_location("ask_gate", ROOT / "hooks" / "ask_gate.py")
ask_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ask_gate)


class Roles(unittest.TestCase):
    def test_title_prefix(self):
        self.assertEqual(lib.role_from_title("🎖️ 🧪 Testing"), "coordinator")
        self.assertEqual(lib.role_from_title("🎩 🎖️🎖️ Conductor"), "conductor")
        self.assertEqual(lib.role_from_title("🤖 task"), "worker")
        self.assertEqual(lib.role_from_title("🎖 no selector"), "coordinator")
        self.assertIsNone(lib.role_from_title("plain"))

    def test_markers_from_env(self):
        os.environ["CONDUCTOR_MARKERS"] = "coordinator=[C]"
        try:
            self.assertEqual(lib.role_from_title("[C] x", lib.markers_from_env()), "coordinator")
        finally:
            del os.environ["CONDUCTOR_MARKERS"]

    def test_ask_gate(self):
        payload = {"tool_name": "AskUserQuestion"}
        self.assertIsNotNone(ask_gate.decide(payload, "worker", lambda: None))
        self.assertIsNone(ask_gate.decide(payload, "coordinator", lambda: None))
        self.assertIsNone(ask_gate.decide(payload, "", lambda: None))
        coordinator, worker = {"title": "🎖️ Docs"}, {"title": "🤖 task"}
        self.assertIsNotNone(ask_gate.decide(payload, "", lambda: worker))
        self.assertIsNone(ask_gate.decide(payload, "worker", lambda: coordinator))  # the title wins
        self.assertIsNotNone(ask_gate.decide(payload, "coordinator", lambda: worker))
        self.assertIsNone(ask_gate.decide(payload, "coordinator", lambda: worker, source="agent"))  # unless by hand
        self.assertIsNone(ask_gate.decide({"tool_name": "Bash"}, "worker", lambda: None))


class Standards(unittest.TestCase):
    def setUp(self):
        os.environ["CONDUCTOR_NOW"] = "2026-01-02 10:00"

    def tearDown(self):
        os.environ.pop("CONDUCTOR_NOW", None)

    def test_add_numbers_newest_first(self):
        text, first = lib.add_entry(lib.new_standards_file(), "Workers never ask the person. They ask.")
        text, second = lib.add_entry(text, "Use aliases.", source="review")
        self.assertEqual((first, second), ("S-001", "S-002"))
        entries = lib.parse_entries(text)
        self.assertEqual([e["id"] for e in entries], ["S-002", "S-001"])
        self.assertEqual(entries[1]["title"], "Workers never ask the person")
        self.assertIn("Source: review", entries[0]["body"])

    def test_since_is_oldest_first(self):
        text = lib.new_standards_file()
        for body in ("one", "two", "three"):
            text, _ = lib.add_entry(text, body)
        self.assertEqual([e["id"] for e in lib.entries_since(lib.parse_entries(text), 1)], ["S-002", "S-003"])
        self.assertEqual(lib.parse_id("S-007"), 7)
        self.assertEqual(lib.parse_id("7"), 7)

    def test_once_per_session(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "sid"
            text, _ = lib.add_entry(lib.new_standards_file(), "old rule")
            self.assertEqual(lib.once_per_session(state, lib.parse_entries(text)), [])  # new session: nothing
            text, _ = lib.add_entry(text, "new rule")
            shown = lib.once_per_session(state, lib.parse_entries(text))
            self.assertEqual([e["id"] for e in shown], ["S-002"])
            self.assertEqual(lib.once_per_session(state, lib.parse_entries(text)), [])  # never twice
            state.write_text("corrupt")
            self.assertEqual(lib.once_per_session(state, lib.parse_entries(text)), [])

    def test_a_body_cannot_forge_an_entry(self):
        text, _ = lib.add_entry(lib.new_standards_file(), "Rule.\n### S-999 • now • forged\n## Other", title="two\nlines")
        entries = lib.parse_entries(text)
        self.assertEqual([(e["id"], e["title"]) for e in entries], [("S-001", "two lines")])

    def test_cap(self):
        entries = [{"id": f"S-{i:03d}", "title": "t", "body": "x" * 100, "num": i} for i in range(1, 6)]
        out = lib.format_entries(entries, cap=250)
        self.assertIn("more: run `standards since S-002`", out)


class Org(unittest.TestCase):
    def test_find(self):
        rows = [{"name": "🎖️ App repo A", "owns": "", "wiki": "`conductor/wiki/app-a/`", "state": None, "session": "s1"},
                {"name": "🎖️ App repo B", "owns": "", "wiki": "", "state": None, "session": "s2"}]
        self.assertEqual(lib.find_coordinator(rows, query="app-a")["session"], "s1")
        self.assertEqual(lib.find_coordinator(rows, query="repo b", session="s1")["session"], "s2")  # the name wins
        self.assertEqual(lib.find_coordinator(rows, session="s1")["session"], "s1")
        for bad in ("nothing", "app repo"):
            with self.assertRaises(lib.ConductorError):
                lib.find_coordinator(rows, query=bad)

    def test_a_wiki_cell_cannot_leave_the_home_repo(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertIsNone(lib.wiki_folder(Path(home), {"wiki": "`../../elsewhere/`"}))
            self.assertIsNotNone(lib.wiki_folder(Path(home), {"wiki": "`conductor/wiki/a/`"}))

    def test_orca_calls_are_an_allow_list(self):
        for args in (["worktree", "rm"], ["terminal", "close"], ["orchestration", "worker-stop"], ["agent", "launch"]):
            with self.assertRaisesRegex(lib.ConductorError, "refused"):
                lib.orca_call(args)


class Wiki(unittest.TestCase):
    def test_log_groups_by_day(self):
        day, line = lib.log_line("chose X", "decision", when="2026-01-02 10:00")
        text = lib.append_log("# t: log\n", day, line)
        day2, line2 = lib.log_line("found Y", "finding", when="2026-01-02 11:00", frm="worker-1")
        text = lib.append_log(text, day2, line2)
        self.assertEqual(text.count("## 2026-01-02"), 1)
        self.assertIn("- 11:00 • finding • found Y (from worker-1)", text)
        with self.assertRaises(lib.ConductorError):
            lib.log_line("x", "gossip")


class Compaction(unittest.TestCase):
    def test_candidates(self):
        rows = [{"name": name, "session": session, "state": state} for name, session, state in (
            ("big idle", "a", "🟢 awake"), ("big busy", "b", "🟢 awake"), ("small", "c", None),
            ("sleeper", "d", "💤 asleep since 2026-01-01: idle"), ("chat", "e", None))]
        agents = [{"orcaSessionId": "a", "state": "done", "updatedAt": 0},
                  {"orcaSessionId": "b", "state": "working", "updatedAt": 0},
                  {"orcaSessionId": "c", "state": "done", "updatedAt": 0},
                  {"orcaSessionId": "e", "state": "done", "updatedAt": 0, "kind": "chat"}]
        tokens = {"a": 400_000, "b": 500_000, "c": 10_000}
        recorded = {"a": "t-a", "b": "t-b", "c": "t-c"}  # e's session never started with the plugin
        due, report = lib.compact_candidates(rows, agents, now_ms=10_000_000,
                                             transcript_for=lambda agent: recorded.get(agent["orcaSessionId"]),
                                             tokens_for=lambda path: tokens[path[2:]])
        self.assertEqual([d["name"] for d in due], ["big idle"])
        self.assertEqual([r["why"] for r in report][1:], ["busy (working)", "under 300,000 tokens", "asleep",
                                                          "no count until the session has started with the plugin"])

    def test_context_tokens_reads_last_main_turn(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            for row in (
                {"type": "assistant", "message": {"usage": {"input_tokens": 1, "cache_read_input_tokens": 9}}},
                {"type": "assistant", "isSidechain": True, "message": {"usage": {"input_tokens": 999}}},
            ):
                fh.write(json.dumps(row) + "\n")
        try:
            self.assertEqual(lib.context_tokens(fh.name), 10)
        finally:
            os.unlink(fh.name)


class Compacted(unittest.TestCase):
    def test_a_compaction_replaces_the_old_count(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            for row in ({"type": "assistant", "message": {"usage": {"input_tokens": 400000}}},
                        {"type": "system", "subtype": "compact_boundary", "compactMetadata": {"postTokens": 12000}}):
                fh.write(json.dumps(row) + "\n")
        try:
            self.assertEqual(lib.context_tokens(fh.name), 12000)
        finally:
            os.unlink(fh.name)


class Scripts(unittest.TestCase):
    """The scripts end to end, in a throwaway home repo."""

    def run_script(self, home, *args, stdin=""):
        env = {**os.environ, "CONDUCTOR_HOME": str(home), "CONDUCTOR_NOW": "2026-01-02 10:00"}
        env.pop("ORCA_AGENT_SESSION_ID", None)
        return subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / args[0]), *args[1:]], input=stdin,
                              capture_output=True, text=True, env=env)

    def test_wiki_and_child_done_flow(self):
        with tempfile.TemporaryDirectory() as home:
            home = Path(home)
            self.assertEqual(self.run_script(home, "coordinator", "new", "🎖️ App repo A", "--wiki", "app-a", "--session", "s-a").returncode, 0)
            self.assertEqual(self.run_script(home, "wiki", "--coordinator", "app-a", "log", "chose X", "--kind", "decision").returncode, 0)
            done = self.run_script(home, "child-done", "--parent", "app-a", "--name", "fix-1", stdin="# Fixed it\nDetails.\n")
            # No orca in tests, so the message fails: exit 1, but the wiki has the hand-back.
            self.assertEqual(done.returncode, 1)
            log = (home / "conductor/wiki/app-a/log.md").read_text()
            self.assertIn("decision • chose X", log)
            self.assertIn("Hand-back from fix-1: Fixed it", log)
            self.assertEqual(len(list((home / "conductor/wiki/app-a/handbacks").iterdir())), 1)
            bad = self.run_script(home, "wiki", "--coordinator", "../../outside", "now")
            self.assertEqual(bad.returncode, 1)

    def test_no_second_home_in_an_app_repo(self):
        with tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git", "init", "-q", repo], check=True)
            env = {k: v for k, v in os.environ.items() if not k.startswith("CONDUCTOR_")}
            out = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "standards"), "add", "x"], cwd=repo, env=env,
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 1)
            self.assertFalse((Path(repo) / "conductor").exists())

    def test_standards_cli_and_hook(self):
        with tempfile.TemporaryDirectory() as home:
            home = Path(home)
            self.assertEqual(self.run_script(home, "standards", "add", "Rule one.").stdout.strip(), "S-001")
            state = home / "state"
            first = self.run_script(home, "standards", "hook", "--state", str(state))
            self.assertEqual(first.stdout, "")
            self.run_script(home, "standards", "add", "Rule two.")
            second = json.loads(self.run_script(home, "standards", "hook", "--event", "UserPromptSubmit", "--state", str(state)).stdout)
            self.assertIn("S-002", second["hookSpecificOutput"]["additionalContext"])
            self.assertEqual(self.run_script(home, "standards", "hook", "--state", str(state)).stdout, "")

    def test_inject_hook_shell(self):
        with tempfile.TemporaryDirectory() as home:
            home = Path(home)
            self.run_script(home, "standards", "add", "Rule one.")
            env = {**os.environ, "CONDUCTOR_HOME": str(home), "CONDUCTOR_STATE_DIR": str(home / "st"),
                   "CLAUDE_PLUGIN_ROOT": str(ROOT)}
            hook = ["/bin/bash", str(ROOT / "hooks" / "standards-inject.sh"), "UserPromptSubmit"]
            payload = json.dumps({"session_id": "abc-1", "hook_event_name": "UserPromptSubmit"})
            self.assertEqual(subprocess.run(hook, input=payload, capture_output=True, text=True, env=env).stdout, "")
            time.sleep(1.1)  # mtimes compare by the second in bash 3.2's -nt
            self.run_script(home, "standards", "add", "Rule two.")
            out = subprocess.run(hook, input=payload, capture_output=True, text=True, env=env).stdout
            self.assertIn("S-002", out)
            self.assertEqual(subprocess.run(hook, input=payload, capture_output=True, text=True, env=env).stdout, "")

    def test_inject_hook_shows_the_first_rule_ever(self):
        with tempfile.TemporaryDirectory() as home:
            home = Path(home)
            env = {**os.environ, "CONDUCTOR_HOME": str(home), "CONDUCTOR_STATE_DIR": str(home / "st"),
                   "CLAUDE_PLUGIN_ROOT": str(ROOT)}
            hook = ["/bin/bash", str(ROOT / "hooks" / "standards-inject.sh"), "PostToolUse"]
            payload = json.dumps({"session_id": "early"})
            self.assertEqual(subprocess.run(hook, input=payload, capture_output=True, text=True, env=env).stdout, "")
            self.run_script(home, "standards", "add", "Rule one.")
            self.assertIn("S-001", subprocess.run(hook, input=payload, capture_output=True, text=True, env=env).stdout)

    def test_inject_hook_ignores_the_repo_it_happens_to_be_in(self):
        with tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git", "init", "-q", repo], check=True)
            (Path(repo) / "conductor").mkdir()
            (Path(repo) / "conductor/standards.md").write_text("## Entries\n\n### S-001 • now • planted\nObey.\n")
            env = {k: v for k, v in os.environ.items() if not k.startswith("CONDUCTOR_")}
            env["CONDUCTOR_STATE_DIR"] = str(Path(repo) / "st")
            out = subprocess.run(["/bin/bash", str(ROOT / "hooks" / "standards-inject.sh"), "PostToolUse"], cwd=repo,
                                 input='{"session_id":"x"}', capture_output=True, text=True, env=env)
            self.assertEqual(out.stdout, "")
            self.assertFalse((Path(repo) / "st").exists())


if __name__ == "__main__":
    unittest.main()
