#!/usr/bin/env -S python3 -I
"""ask_gate: PreToolUse hook on AskUserQuestion. Only some roles may ask the person a question.

For agents the Orca plugin's agent.tool.before hook may not reach (SSH hosts, other launchers, and perhaps
native chats, where neither hook has been verified).

The role, first hit wins:
  1. CONDUCTOR_ROLE when CONDUCTOR_ROLE_SOURCE is `agent` (set by hand on the agent before it launched),
  2. the title's leading marker, from this agent's `orca agent list` row (found by session id, else pane key),
  3. CONDUCTOR_ROLE (the workspace's role when the agent launched),
  4. the worker marker on the workspace's display name, as child-start sets it.
The Orca plugin sends its settings and the role at launch: CONDUCTOR_GATE, CONDUCTOR_ASK_ROLES, CONDUCTOR_MARKERS.
This hook cannot see a role or setting changed in Orca after that, and a chat gets no launch env at all.

An agent with no known role is allowed. A role outside CONDUCTOR_ASK_ROLES (default conductor,coordinator)
is denied with a reason that points it at `orca orchestration ask`. Never fails closed on an error.
"""
import json, os, sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import conductor_lib as lib  # noqa: E402

# `orca agent list` has taken over 2 s on a busy machine. hooks.json allows this hook more than this.
LIST_TIMEOUT = 8


def listed_self():
    try:
        return lib.self_agent(timeout=LIST_TIMEOUT)
    except lib.ConductorError:
        return None


def decide(payload, env_role, lookup=listed_self, source=""):
    if payload.get("tool_name") != "AskUserQuestion":
        return None
    role = env_role if env_role in lib.ROLES else None
    if not (role and source == "agent"):
        agent, markers = lookup() or {}, lib.markers_from_env()
        by_name = lib.role_from_title(agent.get("workspace"), markers)
        role = lib.role_from_title(agent.get("title"), markers) or role or (by_name if by_name == "worker" else None)
    return lib.ask_deny_reason(role, lib.ask_roles_from_env())


def main():
    try:
        if os.environ.get("CONDUCTOR_GATE", "").strip().lower() == "off":
            return 0
        payload = json.loads(sys.stdin.read() or "{}")
        reason = decide(payload, os.environ.get("CONDUCTOR_ROLE", "").strip().lower(),
                        source=os.environ.get("CONDUCTOR_ROLE_SOURCE", "").strip().lower())
    except Exception:  # noqa: BLE001
        return 0
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
