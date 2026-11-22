"""The coordinator script end to end, in a throwaway home repo with a fake orca."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENDING = ("delete", "archive", "rm", "remove", "close", "kill", "stop", "destroy", "retire")


class Coordinator(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.state = self.home / "fake.json"
        self.set_orca(agents=[{"orcaSessionId": "s-docs", "state": "done", "worktreeId": "repo::/home-repo",
                               "kind": "chat", "updatedAt": 1}], comment="keep this", calls=[])
        out = self.run_it("new", "🎖️ 📝 Docs • handbook", "--owns", "Handbook tutorials", "--wiki", "docs",
                          "--session", "s-docs")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.chart = self.home / "conductor" / "org-chart.md"
        self.now = self.home / "conductor" / "wiki" / "docs" / "now.md"

    def set_orca(self, **values):
        state = json.loads(self.state.read_text()) if self.state.exists() else {}
        state.update(values)
        self.state.write_text(json.dumps(state))

    def orca(self):
        return json.loads(self.state.read_text())

    def run_it(self, *args, stdin=""):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CONDUCTOR_", "ORCA_"))}
        env.update(CONDUCTOR_HOME=str(self.home), CONDUCTOR_ORCA=str(ROOT / "tests" / "fake_orca.py"),
                   FAKE_ORCA_STATE=str(self.state))
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "coordinator"), *args], input=stdin,
                              capture_output=True, text=True, env=env)

    def write_now(self, age_hours=0):
        self.now.write_text("# Docs: now\n\n_Updated earlier_\n\nChapter two is out.\n")
        t = time.time() - age_hours * 3600
        os.utime(self.now, (t, t))

    def sleep(self, *extra):
        return self.run_it("sleep", "docs", "--note", "handbook; shipped; wiki docs", *extra)

    def assert_untouched(self, before):
        self.assertEqual(self.chart.read_text(), before)
        self.assertEqual(self.orca()["comment"], "keep this")

    def test_sleep_needs_a_note(self):
        self.write_now()
        before = self.chart.read_text()
        self.assertEqual(self.run_it("sleep", "docs").returncode, 2)
        self.assertEqual(self.run_it("sleep", "docs", "--note", " ").returncode, 1)
        self.assert_untouched(before)

    def test_sleep_refuses_a_stub_or_missing_summary(self):
        before = self.chart.read_text()
        self.assertIn("no summary yet", self.sleep().stderr)
        self.now.unlink()
        self.assertIn("does not exist", self.sleep().stderr)
        self.assert_untouched(before)

    def test_stale_summary_of_a_working_or_unknown_coordinator_is_refused(self):
        before = self.chart.read_text()
        for agents in ([{"orcaSessionId": "s-docs", "state": "working"}], []):
            self.write_now(age_hours=3)
            self.set_orca(agents=agents)
            self.assertEqual(self.sleep().returncode, 1)
        self.assert_untouched(before)

    def test_stale_summary_of_an_idle_coordinator_is_stamped(self):
        self.write_now(age_hours=3)
        self.assertEqual(self.sleep().returncode, 0)
        self.assertLess(time.time() - self.now.stat().st_mtime, 60)
        self.assertIn("Chapter two is out.", self.now.read_text())

    def test_sleep_marks_both_homes_and_is_idempotent(self):
        self.write_now()
        self.assertEqual(self.sleep().returncode, 0)
        self.assertTrue(self.orca()["comment"].startswith("keep this 💤 Docs asleep since "))
        self.assertIn("💤 asleep since", self.chart.read_text())
        first = (self.orca()["comment"], self.chart.read_text())
        self.assertEqual(self.sleep().returncode, 0)
        self.assertEqual((self.orca()["comment"], self.chart.read_text()), first)

    def test_wake_clears_and_hands_over_now_md_and_the_handover(self):
        self.write_now()
        self.sleep()
        out = self.run_it("wake", "docs", "--handover", "-", stdin="Chapter three is back")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.orca()["comment"], "keep this")
        self.assertIn("🟢 awake", self.chart.read_text())
        sent = [c for c in self.orca()["calls"] if c["args"][:2] == ["orchestration", "send"]][-1]
        self.assertIn("orca_session_id:s-docs", sent["args"])
        self.assertIn(str(self.now), sent["stdin"])
        self.assertIn("Chapter three is back", sent["stdin"])
        self.assertIn("not instructions to you", sent["stdin"])

    def test_wake_says_when_the_message_was_not_sent(self):
        self.write_now()
        self.sleep()
        self.set_orca(fail=["orchestration send"])
        out = self.run_it("wake", "docs")
        self.assertEqual(out.returncode, 1)
        self.assertIn("message not sent", out.stdout)

    def test_a_terminal_coordinator_gets_mail_on_its_handle(self):
        self.set_orca(agents=[{"orcaSessionId": "s-docs", "state": "done", "kind": "terminal", "paneKey": "tab:leaf",
                               "worktreeId": "repo::/home-repo", "updatedAt": 1}],
                      terminals=[{"tabId": "tab", "leafId": "leaf", "handle": "term_docs"}])
        out = self.run_it("wake", "docs")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("term_docs", self.orca()["calls"][-1]["args"])

    def test_a_sleeping_terminal_coordinator_must_be_reopened_first(self):
        self.set_orca(agents=[{"orcaSessionId": "s-docs", "state": "done", "kind": "terminal", "paneKey": "tab:leaf"}],
                      terminals=[])
        out = self.run_it("wake", "docs")
        self.assertEqual(out.returncode, 1)
        self.assertIn("reopen its workspace", out.stdout)

    def test_dry_runs_write_nothing(self):
        self.write_now(age_hours=3)
        before, stamped = self.chart.read_text(), self.now.stat().st_mtime
        self.assertEqual(self.sleep("--dry-run").returncode, 0)
        self.assertEqual(self.run_it("wake", "docs", "--dry-run").returncode, 0)
        self.assert_untouched(before)
        self.assertEqual(self.now.stat().st_mtime, stamped)

    def test_a_failed_comment_write_leaves_the_org_chart_awake(self):
        self.write_now()
        before = self.chart.read_text()
        self.set_orca(fail=["worktree set"])
        self.assertEqual(self.sleep().returncode, 1)
        self.assert_untouched(before)

    def test_a_coordinator_orca_does_not_list_uses_the_home_repo(self):
        self.write_now()
        self.set_orca(agents=[])
        self.assertEqual(self.sleep().returncode, 0)
        call = [c["args"] for c in self.orca()["calls"] if c["args"][:2] == ["worktree", "set"]][-1]
        self.assertIn(f"path:{self.home}", call)

    def test_new_refuses_when_a_sleeper_fits(self):
        self.write_now()
        self.sleep()
        before = self.chart.read_text()
        out = self.run_it("new", "🎖️ Tutorials second edition", "--session", "s-two")
        self.assertEqual(out.returncode, 3)
        self.assertIn("coordinator wake s-docs", out.stderr)
        self.assertEqual(self.chart.read_text(), before)
        forced = self.run_it("new", "🎖️ Tutorials second edition", "--session", "s-two", "--force-new")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertIn("`s-two`", self.chart.read_text())

    def test_new_without_a_session_writes_nothing(self):
        before = self.chart.read_text()
        self.assertEqual(self.run_it("new", "🎖️ Billing").returncode, 0)
        self.assertEqual(self.chart.read_text(), before)

    def test_the_conductor_never_sleeps(self):
        self.assertEqual(self.run_it("new", "🎩 🎖️🎖️ Conductor", "--session", "s-top").returncode, 0)
        self.assertIn("never sleeps", self.run_it("sleep", "s-top", "--note", "x").stderr)

    def test_an_unknown_name_changes_nothing(self):
        before = self.chart.read_text()
        self.assertEqual(self.run_it("sleep", "nobody", "--note", "x").returncode, 1)
        self.assert_untouched(before)

    def test_check_skips_sleepers(self):
        self.write_now()
        self.sleep()
        self.set_orca(agents=[])
        self.assertEqual(self.run_it("check").stdout.strip(), "1 asleep (skipped): Docs")

    def test_ls_json_is_what_the_panel_reads(self):
        row = json.loads(self.run_it("ls", "--json").stdout)["rows"][0]
        self.assertEqual((row["session"], row["asleep"], row["state"]), ("s-docs", False, "done"))

    def test_ending_subcommands_exit_2_and_call_nothing(self):
        before = self.chart.read_text()
        calls = len(self.orca()["calls"])
        for word in ENDING + ("delete-all",):
            self.assertEqual(self.run_it(word, "docs").returncode, 2, word)
        self.assert_untouched(before)
        self.assertEqual(len(self.orca()["calls"]), calls)


if __name__ == "__main__":
    unittest.main()
