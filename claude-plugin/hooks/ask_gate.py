#!/usr/bin/env python3
"""ask_gate: PreToolUse hook on AskUserQuestion. Only some roles may ask the person a question.

For agents the Orca plugin's agent.tool.before hook may not reach (SSH hosts, other launchers, and perhaps
native chats, where neither hook has been verified).
The role comes from, in order (the same order as the Orca plugin):
  1. the chat title's leading marker, read from `orca agent list --json` by ORCA_AGENT_SESSION_ID,
  2. CONDUCTOR_ROLE (the Orca plugin sets it at launch from the workspace's role).
An agent with no known role is allowed. A role outside CONDUCTOR_ASK_ROLES (default conductor,coordinator)
is denied with a reason that points it at `orca orchestration ask`. Never fails closed on an error.
"""
import json, os, sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import conductor_lib as lib  # noqa: E402


def title_role():
    sid = os.environ.get("ORCA_AGENT_SESSION_ID", "").strip()
    if not sid:
        return None
    try:
        agents = lib.orca_agents(timeout=2)
    except lib.ConductorError:
        return None
    for agent in agents:
        if agent.get("orcaSessionId") == sid:
            return lib.role_from_title(agent.get("title"), lib.markers_from_env())
    return None


def decide(payload, env_role, lookup=title_role):
    if payload.get("tool_name") != "AskUserQuestion":
        return None
    role = lookup() or (env_role if env_role in lib.ROLES else None)
    return lib.ask_deny_reason(role, lib.ask_roles_from_env())


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        reason = decide(payload, os.environ.get("CONDUCTOR_ROLE", "").strip().lower())
    except Exception:  # noqa: BLE001
        return 0
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
