#!/usr/bin/env python3
"""A stand-in for the orca CLI in tests. It records every call and never talks to Orca.

State is the JSON file FAKE_ORCA_STATE names: agents, terminals, comment, fail (commands to fail), calls.
"""
import json
import os
import sys

path = os.environ.get("FAKE_ORCA_STATE")
if not path:
    sys.exit("fake orca: no FAKE_ORCA_STATE")
with open(path, encoding="utf-8") as fh:
    state = json.load(fh)
args = sys.argv[1:]
words = " ".join(args[:2])
body = sys.stdin.read() if "--body-file" in args and args[args.index("--body-file") + 1] == "-" else ""
state.setdefault("calls", []).append({"args": args, "stdin": body})
code, result = 0, {}
if words in state.get("fail", []):
    code = 1
elif words == "agent list":
    result = {"agents": state.get("agents", [])}
elif words == "worktree show":
    result = {"worktree": {"comment": state.get("comment", "")}}
elif words == "worktree set":
    state["comment"] = args[args.index("--comment") + 1]
elif words == "terminal list":
    result = {"terminals": state.get("terminals", [])}
elif words == "orchestration send":
    # As Orca does: a terminal agent's session id is refused, only its handle takes mail.
    to = args[args.index("--to") + 1]
    refused = [f"orca_session_id:{a.get('orcaSessionId')}" for a in state.get("agents", [])
               if a.get("kind") == "terminal"]
    code = 1 if to in refused else 0
else:
    code = 1
with open(path, "w", encoding="utf-8") as fh:
    json.dump(state, fh)
print(json.dumps({"ok": code == 0, "result": result}))
sys.exit(code)
