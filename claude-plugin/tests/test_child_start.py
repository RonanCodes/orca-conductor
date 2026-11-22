"""child-start: one supervised child worker. Only the fake and --dry-run: no test starts a real worker."""
import os
import subprocess
import unittest

from support import CHAT_ENV, ROOT, TERM_ENV, HomeCase, agent


class ChildStart(HomeCase):
    def start(self, *args, env=TERM_ENV, stdin="Fix the flaky index test. Done = it passes 20 times."):
        return self.run_script("child-start", "--name", "fix index", *args, env=env, stdin=stdin)

    def started(self, *args, **kw):
        out = self.start(*args, **kw)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        call = self.calls("orchestration worker-start")[-1]
        argv = call["args"][2:]
        flags = {a: argv[i + 1] for i, a in enumerate(argv) if a.startswith("--") and i + 1 < len(argv)}
        return flags, call["stdin"]

    def test_it_starts_a_child_worktree_worker(self):
        flags, _ = self.started("--repo", "name:app-a")
        self.assertEqual(flags["--worktree"], "new-child")
        self.assertEqual(flags["--comment"], "child of Search")
        self.assertEqual(flags["--repo"], "name:app-a")
        self.assertEqual(flags["--agent"], "claude")
        self.assertEqual(flags["--spec-file"], "-")
        self.assertEqual(flags["--display-name"], "🤖 fix index")
        self.assertEqual(flags["--task-title"], "🤖 fix index")
        self.assertEqual(flags["--name"], "fix-index")

    def test_a_chat_coordinator_is_found_too(self):
        self.assertEqual(self.started(env=CHAT_ENV)[0]["--comment"], "child of Docs")

    def test_an_explicit_coordinator_wins(self):
        self.assertEqual(self.started("--coordinator", "docs")[0]["--comment"], "child of Docs")

    def test_the_model_is_always_explicit_by_role(self):
        self.assertEqual(self.started()[0]["--model"], "sonnet")
        flags, _ = self.started("--role", "reviewer")
        self.assertEqual(flags["--model"], "opus")
        self.assertNotIn("--effort", flags)
        flags, _ = self.started("--role", "reviewer", "--model", "haiku", "--effort", "low")
        self.assertEqual((flags["--model"], flags["--effort"]), ("haiku", "low"))

    def test_a_pinned_model_id_is_refused(self):
        self.assertEqual(self.start("--model", "claude-sonnet-4-5").returncode, 1)
        self.assertEqual(self.calls("orchestration worker-start"), [])

    def test_an_empty_spec_is_refused(self):
        for spec in ("", " \n"):
            out = self.start(stdin=spec)
            self.assertEqual(out.returncode, 1)
            self.assertIn("spec is empty", out.stderr)
        self.assertEqual(self.calls("orchestration worker-start"), [])

    def test_no_coordinator_is_refused(self):
        out = self.start(env={})
        self.assertEqual(out.returncode, 1)
        self.assertIn("Which coordinator", out.stderr)
        self.assertEqual(self.calls("orchestration worker-start"), [])

    def test_the_spec_says_how_to_ask_and_the_exact_hand_back(self):
        _, spec = self.started()
        self.assertTrue(spec.startswith("Fix the flaky index test."))
        self.assertIn("orca orchestration ask --question", spec)
        line = next(x.strip() for x in spec.splitlines() if "child-done" in x and "--parent" in x)
        self.assertIn(str(ROOT / "scripts" / "child-done"), line)
        self.assertIn("CONDUCTOR_HOME=", line)
        self.assertIn("--parent search", line)
        # Run that line as the worker would: no home in its environment, in another folder.
        env = {k: v for k, v in self.env.items() if k != "CONDUCTOR_HOME"}
        done = subprocess.run(line, shell=True, cwd=str(self.top), env=env, input="Fixed.", capture_output=True,
                              text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(len(os.listdir(self.home / "conductor" / "wiki" / "search" / "handbacks")), 1)

    def test_the_gate_sees_the_child_as_a_worker(self):
        flags, _ = self.started()
        for title in (None, "Index test", flags["--task-title"]):
            self.set_orca(agents=[agent("terminal", "orca-terminal-child", "tab-child:leaf-child", title,
                                        workspace=flags["--display-name"], state="working")])
            self.assertFalse(self.asks({"ORCA_PANE_KEY": "tab-child:leaf-child"}))
        self.set_orca(agents=[agent("chat", "claude_chat-child", "chat-child:leaf-child", None,
                                    workspace=flags["--display-name"])])
        self.assertFalse(self.asks({"ORCA_AGENT_SESSION_ID": "claude_chat-child"}))

    def test_dry_run_starts_nothing(self):
        out = self.start("--dry-run")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("worker-start", out.stdout)
        self.assertIn("child-done", out.stdout)
        self.assertEqual(self.calls("orchestration worker-start"), [])

    def test_a_failed_start_says_not_to_start_it_again(self):
        self.set_orca(fail=["orchestration worker-start"])
        out = self.start()
        self.assertEqual(out.returncode, 1)
        self.assertIn("worker-list", out.stderr)

    def test_worker_start_is_the_only_new_orca_command(self):
        self.assertEqual(self.started()[0]["--agent"], "claude")
        used = {" ".join(c["args"][:2]) for c in self.orca()["calls"]}
        self.assertEqual(used, {"agent list", "orchestration worker-start"})

    def test_a_name_cannot_inject_into_the_hand_back_command(self):
        out = self.run_script("child-start", "--name", "x; touch pwned $(touch pwned2) 'q", env=TERM_ENV, stdin="Task")
        self.assertEqual(out.returncode, 0, out.stderr)
        spec = self.calls("orchestration worker-start")[-1]["stdin"]
        line = next(x.strip() for x in spec.splitlines() if "child-done" in x and "--parent" in x)
        subprocess.run(line, shell=True, cwd=str(self.top), env=self.env, input="Done.", capture_output=True, text=True)
        self.assertEqual([p.name for p in self.top.iterdir() if "pwned" in p.name], [])
        self.assertEqual(len(os.listdir(self.home / "conductor" / "wiki" / "search" / "handbacks")), 1)


if __name__ == "__main__":
    unittest.main()
