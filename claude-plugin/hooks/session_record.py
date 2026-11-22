#!/usr/bin/env -S python3 -I
"""session_record: records which transcript this agent writes, for compact-check.

An Orca session id does not name a Claude transcript, so this hook saves the payload's transcript_path under
the agent's identity (session id for a chat, pane key for a terminal agent). It runs at SessionStart, and
again at each prompt so the outer session takes the record back after a nested `claude` in the same pane.
Silent, and always exits 0.
"""
import json, sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import conductor_lib as lib  # noqa: E402


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not payload.get("agent_id"):  # a subagent's transcript is not the agent's
            lib.record_transcript(payload.get("transcript_path"), payload.get("session_id"))
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
