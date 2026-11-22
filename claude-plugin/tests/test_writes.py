"""Every read-modify-write takes a lock, and a standard written during the hook is still shown."""
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from support import CHAT_ID, ROOT, HomeCase


class Locks(HomeCase):
    def assert_waits_for_the_lock(self, folder, *cmd, stdin=""):
        fd = os.open(str(folder), os.O_RDONLY)
        fcntl.flock(fd, fcntl.LOCK_EX)
        proc = subprocess.Popen([str(ROOT / "scripts" / cmd[0]), *cmd[1:]], env=self.env, text=True,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            proc.stdin.write(stdin)
            proc.stdin.close()
            time.sleep(2)
            self.assertIsNone(proc.poll(), f"{' '.join(cmd)} wrote without waiting for the lock")
        finally:
            os.close(fd)
            proc.stdin = None
            _, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0, err)

    @property
    def conductor(self):
        return self.home / "conductor"

    @property
    def wiki(self):
        return self.conductor / "wiki" / "docs"

    def test_standards_add_takes_the_lock(self):
        self.assert_waits_for_the_lock(self.conductor, "standards", "add", "A rule.")

    def test_wiki_log_takes_the_lock(self):
        self.assert_waits_for_the_lock(self.wiki, "wiki", "--coordinator", "docs", "log", "x", "--kind", "finding")

    def test_wiki_now_takes_the_lock(self):
        self.assert_waits_for_the_lock(self.wiki, "wiki", "--coordinator", "docs", "now", "--set", "-", stdin="Body")

    def test_child_done_takes_the_lock(self):
        self.assert_waits_for_the_lock(self.wiki, "child-done", "--parent", "docs", stdin="Done")

    def test_coordinator_new_takes_the_lock(self):
        self.assert_waits_for_the_lock(self.conductor, "coordinator", "new", "Billing", "--session", "claude_chat-b")

    def test_coordinator_sleep_takes_the_lock(self):
        self.assert_waits_for_the_lock(self.conductor, "coordinator", "sleep", "docs", "--note", "idle")

    def test_coordinator_wake_takes_the_lock(self):
        self.assert_waits_for_the_lock(self.conductor, "coordinator", "wake", "docs")

    def test_the_stale_now_stamp_takes_the_wiki_lock(self):
        old = time.time() - 3 * 3600
        os.utime(self.wiki / "now.md", (old, old))
        self.assert_waits_for_the_lock(self.wiki, "coordinator", "sleep", "docs", "--note", "idle")


class Parallel(HomeCase):
    def together(self, count, call):
        with ThreadPoolExecutor(max_workers=count) as pool:
            return list(pool.map(call, range(count)))

    def test_20_parallel_standards_keep_20_rules_and_ids(self):
        out = self.together(20, lambda i: self.run_script("standards", "add", f"Rule {i}."))
        self.assertEqual(len({o.stdout.strip() for o in out}), 20)
        self.assertEqual((self.home / "conductor" / "standards.md").read_text().count("### S-"), 20)

    def test_20_parallel_logs_keep_20_lines(self):
        self.together(20, lambda i: self.run_script("wiki", "--coordinator", "docs", "log", f"claim {i}",
                                                    "--kind", "finding"))
        self.assertEqual((self.home / "conductor" / "wiki" / "docs" / "log.md").read_text().count("• finding •"), 20)

    def test_20_parallel_hand_backs_keep_20_files_and_lines(self):
        out = self.together(20, lambda i: self.run_script("child-done", "--parent", "docs", "--name", "w",
                                                          stdin=f"Summary {i}"))
        self.assertEqual([o.returncode for o in out], [0] * 20)
        wiki = self.home / "conductor" / "wiki" / "docs"
        self.assertEqual(len(list((wiki / "handbacks").iterdir())), 20)
        self.assertEqual((wiki / "log.md").read_text().count("Hand-back from w"), 20)

    def test_parallel_sleeps_on_one_comment_keep_both(self):
        self.together(2, lambda i: self.run_script("coordinator", "sleep", ("docs", "search")[i], "--note", "idle"))
        self.assertEqual(self.orca()["comment"].count("asleep since"), 2)
        self.assertEqual(self.chart.read_text().count("💤 asleep since"), 2)

    def test_parallel_new_keeps_every_row(self):
        self.together(8, lambda i: self.run_script("coordinator", "new", f"Topic{i}", "--session", f"claude_chat-{i}"))
        self.assertEqual(self.chart.read_text().count("`claude_chat-"), 8 + 1)  # and Docs
        self.assertIn(CHAT_ID, self.chart.read_text())


class StandardsHook(HomeCase):
    def hook(self):
        return subprocess.run(["/bin/bash", str(ROOT / "hooks" / "standards-inject.sh"), "PostToolUse"],
                              input=json.dumps({"session_id": "session-1"}), capture_output=True, text=True,
                              env=self.env).stdout

    def test_a_write_between_the_read_and_the_stat_is_shown(self):
        self.run_script("standards", "add", "First rule.")
        path = self.home / "conductor" / "standards.md"
        old = time.time() - 60
        os.utime(path, (old, old))
        loader = importlib.machinery.SourceFileLoader("standards_script", str(ROOT / "scripts" / "standards"))
        script = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(script)
        real_read = script.read

        def read_then_someone_writes(p):
            text = real_read(p)
            self.run_script("standards", "add", "Written during the hook.")
            return text

        args = mock.Mock(event="PostToolUse", state=str(self.top / "state" / "session-1"))
        with mock.patch.object(script, "read", read_then_someone_writes), \
                mock.patch.dict(os.environ, {"CONDUCTOR_STANDARDS_FILE": str(path)}):
            script.cmd_hook(args)
        self.assertIn("Written during the hook", self.hook())

    def test_a_second_write_in_the_same_second_is_shown(self):
        self.assertEqual(self.hook(), "")
        self.run_script("standards", "add", "Old rule.")
        self.hook()
        path = self.home / "conductor" / "standards.md"
        # Wait for the start of a second, so both writes and the hook between them share it.
        time.sleep(1.02 - time.time() % 1)
        first = path.read_text()
        path.write_text(first.replace("## Entries\n\n", "## Entries\n\n### S-002 • now • Second\nSecond rule.\n\n"))
        self.assertIn("Second rule", self.hook())
        path.write_text(path.read_text().replace("## Entries\n\n",
                                                 "## Entries\n\n### S-003 • now • Third\nThird rule.\n\n"))
        self.assertIn("Third rule", self.hook())


if __name__ == "__main__":
    unittest.main()
