#!/usr/bin/env -S python3 -I
"""A stand-in for the orca CLI in tests. It records every call and never talks to Orca.

State is the JSON file FAKE_ORCA_STATE names: agents, terminals, comment, fail (commands to fail),
delay (seconds before `agent list` answers), calls. The shapes are the real CLI's (see support.py).
"""
import fcntl
import json
import os
import sys
import time

path = os.environ.get("FAKE_ORCA_STATE")
if not path:
    sys.exit("fake orca: no FAKE_ORCA_STATE")


def update(change):
    with open(path + ".lock", "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
        out = change(state)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    return out


args = sys.argv[1:]
words = " ".join(args[:2])
flag = {"orchestration send": "--body-file", "orchestration worker-start": "--spec-file"}.get(words)
body = sys.stdin.read() if flag in args and args[args.index(flag) + 1] == "-" else ""


def answer(state):
    state.setdefault("calls", []).append({"args": args, "stdin": body})
    code, result = 0, {}
    if words in state.get("fail", []):
        code = 1
    elif words == "agent list":
        result = {"agents": state.get("agents", []), "truncated": False}
    elif words == "terminal list":
        result = {"terminals": state.get("terminals", [])}
    elif words == "worktree show":
        result = {"worktree": {"comment": state.get("comment", "")}}
    elif words == "worktree set":
        state["comment"] = args[args.index("--comment") + 1]
    elif words == "orchestration send":
        # As Orca does: a terminal agent's session id is refused, only its handle takes mail.
        to = args[args.index("--to") + 1]
        refused = [f"orca_session_id:{a.get('orcaSessionId')}" for a in state.get("agents", [])
                   if a.get("kind") == "terminal"]
        code = 1 if to in refused else 0
    elif words == "orchestration worker-start":
        result = {"state": "ready", "dispatchId": "dispatch-1", "taskId": "task-1", "runId": "run-1"}
    else:
        code = 1
    return code, result, state.get("delay", 0) if words == "agent list" else 0


code, result, delay = update(answer)
time.sleep(delay)
print(json.dumps({"ok": code == 0, "result": result}))
sys.exit(code)
