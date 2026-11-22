"""No entry point may import Python from the folder it runs in, which may be a repo you do not trust.

Every entry point is found, not listed: the commands in hooks.json, every executable file, the hand-back
command child-start writes, and the Orca plugin's spawn. Each runs from a folder with a planted json.py and
pathlib.py. A static check catches a new invocation that those runs would not reach.
"""
import json
import os
import re
import shlex
import stat
import subprocess
import sys

from support import ROOT, HomeCase

REPO = ROOT.parent
SHEBANG = "#!/usr/bin/env -S python3 -I"
GENERATED = {".git", ".orca", "node_modules", "__pycache__"}
# What an executable needs to get past its imports and exit 0. The default is --help.
ARGS = {"fake_orca.py": ["agent", "list", "--json"], "standards-inject.sh": ["UserPromptSubmit"]}

# Python followed by a flag, a path or a .py file, in code, docs and skills. Prose that only names it does not match.
COMMAND = re.compile(r"\bpython(?:\d(?:\.\d+)?)?[ \t]+(?=[-\"'$/.~<\\]|[\w.-]+/|[\w-]+\.py\b)(\S+)")
# An argv that starts with Python, in Python or TypeScript.
ARGV = re.compile(r"(?:['\"]python[\d.]*['\"]|\bsys\.executable)\s*,\s*\[?\s*([^,\]\s]+)")


def repo_files():
    for folder, dirs, names in os.walk(REPO):
        dirs[:] = sorted(d for d in dirs if d not in GENERATED)
        for name in sorted(names):
            if name != ".git" and not name.endswith(".pyc"):
                yield REPO / os.path.relpath(os.path.join(folder, name), REPO)


def executables():
    return [p for p in repo_files() if p.stat().st_mode & stat.S_IXUSR]


def hook_commands():
    events = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    return [(event, hook["command"]) for event, groups in events.items() for group in groups for hook in group["hooks"]]


class Planted(HomeCase):
    def setUp(self):
        super().setUp()
        self.repo = self.top / "untrusted repo"
        self.repo.mkdir()
        self.marker = self.top / "planted code ran"
        for module in ("json", "pathlib"):
            (self.repo / f"{module}.py").write_text(f"open({str(self.marker)!r}, 'a').write({module!r})\n")
        (self.home / "conductor" / "standards.md").write_text("# Standards\n")
        # `python3` is the Python that runs the tests, so each version tests its own shebang and hooks.
        shims = self.top / "bin"
        shims.mkdir()
        shim = shims / "python3"
        shim.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
        shim.chmod(0o755)
        self.env["PATH"] = f"{shims}{os.pathsep}{os.environ['PATH']}"
        self.env.pop("PYTHONPATH", None)
        self.runs = 0

    def search_paths(self):
        absent = str(self.top / "absent")
        return {"unset": None, "dot": ".", "empty first": os.pathsep + absent, "empty last": absent + os.pathsep}

    def check(self, what, command, shell=False, event="UserPromptSubmit"):
        for label, value in self.search_paths().items():
            self.runs += 1
            if self.marker.exists():
                self.marker.unlink()
            # A fresh state folder, so the standards hook reaches Python every time.
            state = self.top / f"state-{self.runs}"
            env = {**self.env, "CONDUCTOR_STATE_DIR": str(state)}
            if value is not None:
                env["PYTHONPATH"] = value
            payload = {"session_id": "claude-session", "hook_event_name": event, "tool_name": "AskUserQuestion"}
            done = subprocess.run(command, shell=shell, cwd=str(self.repo), env=env, input=json.dumps(payload),
                                  capture_output=True, text=True, timeout=60)
            with self.subTest(entry=what, search_path=label):
                self.assertFalse(self.marker.exists(), "planted code ran")
                self.assertEqual(done.returncode, 0, done.stderr)
                if "standards-inject" in what:
                    self.assertTrue((state / "claude-session").exists(), "the hook did not reach its script")

    def test_the_plant_works_without_isolation(self):
        plain = [sys.executable]
        subprocess.run(plain + ["-c", "import json"], cwd=str(self.repo), env=self.env, capture_output=True)
        self.assertTrue(self.marker.exists())

    def test_every_hook_command(self):
        commands = hook_commands()
        self.assertTrue(commands)
        for event, command in commands:
            self.check(f"{event}: {command}", command, shell=True, event=event)

    def test_every_executable_by_path(self):
        found = executables()
        self.assertTrue(found)
        for path in found:
            self.check(str(path.relative_to(REPO)), [str(path), *ARGS.get(path.name, ["--help"])])

    def test_the_hand_back_command_a_worker_runs(self):
        out = self.run_script("child-start", "--name", "task", "--coordinator", "docs", "--spec", "Do it.", "--dry-run")
        self.assertEqual(out.returncode, 0, out.stderr)
        line = next(x.strip() for x in out.stdout.splitlines() if x.strip().startswith("CONDUCTOR_HOME="))
        self.check("hand-back", line, shell=True)

    def test_the_orca_plugins_spawn(self):
        cli = (REPO / "orca-plugin" / "src" / "cli.ts").as_uri()
        setup = {"script": str(ROOT / "scripts" / "coordinator"), "home": str(self.home),
                 "markers": {"conductor": "🎩", "coordinator": "🎖️", "worker": "🤖"}}
        code = (f"import {{ runCoordinator }} from {json.dumps(cli)};\n"
                f"const out = await runCoordinator({json.dumps(setup)}, ['ls']);\n"
                "if (!out.ok) { console.error(out.output); process.exit(1) }\n")
        self.check("spawn", ["node", "--input-type=module", "-e", code])


class NewEntryPoints(HomeCase):
    def test_every_executable_has_a_known_isolated_interpreter(self):
        for path in executables():
            with self.subTest(file=str(path.relative_to(REPO))):
                self.assertIn(path.read_text().splitlines()[0], (SHEBANG, "#!/bin/bash"))

    def test_every_python_shebang_is_isolated(self):
        for path in repo_files():
            first = path.read_bytes().split(b"\n", 1)[0].decode("utf-8", "replace")
            if first.startswith("#!") and "python" in first:
                with self.subTest(file=str(path.relative_to(REPO))):
                    self.assertEqual(first, SHEBANG)

    def test_every_written_invocation_is_isolated(self):
        for path in repo_files():
            text = path.read_bytes().decode("utf-8", "replace")
            for pattern in (COMMAND, ARGV):
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    with self.subTest(at=f"{path.relative_to(REPO)}:{line}"):
                        self.assertEqual(match.group(1).strip("'\"`"), "-I", match.group(0))

    def test_the_orca_plugin_starts_one_program_in_one_place(self):
        starts = []
        for path in sorted((REPO / "orca-plugin" / "src").glob("*.ts*")):
            if path.name.endswith(".d.ts"):
                continue
            text = path.read_text()
            starts += [(path.name, found) for found in
                       re.findall(r"(?<![.\w])(?:spawn|spawnSync|exec|execFile|execSync|execFileSync|fork)\(", text)]
            if "child_process" in text:
                self.assertEqual(path.name, "cli.ts", "a new file starts programs: test it here")
        self.assertEqual(starts, [("cli.ts", "spawn(")], "a new spawn: run it from the planted folder here")
