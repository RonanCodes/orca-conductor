#!/bin/bash
# standards-inject: show each new standards entry once to every running Claude Code session.
#
#   standards-inject.sh <SessionStart|UserPromptSubmit|PostToolUse>   (hook JSON on stdin)
#
# Compares the standards file's mtime with this session's state file using bash builtins only, so the
# no-change path starts no process. When the file is newer (or the session is new) it runs
# `scripts/standards hook`, which prints hookSpecificOutput.additionalContext with the entries this session
# has not seen, or nothing. A new session is marked as having seen everything up to now.
#
# Never blocks: always exits 0, silent on any error. bash 3.2 compatible.
# Env: CONDUCTOR_STANDARDS_FILE or CONDUCTOR_HOME. With neither, the hook does nothing: it must never take
#      rules from whichever repo the session happens to be in, because that repo may not be yours.
#      CONDUCTOR_STATE_DIR (default ~/.local/state/orca-conductor/standards).
event="${1:-PostToolUse}"
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
d="${CONDUCTOR_STATE_DIR:-$HOME/.local/state/orca-conductor/standards}"

input=""
IFS= read -r -d '' -n 4096 input 2>/dev/null
re='"session_id"[[:space:]]*:[[:space:]]*"([A-Za-z0-9._-]+)"'
if [[ $input =~ $re ]]; then
  sid="${BASH_REMATCH[1]}"
else
  rest="$(cat 2>/dev/null)"
  [[ $input$rest =~ $re ]] || exit 0
  sid="${BASH_REMATCH[1]}"
fi

if [ -n "$CONDUCTOR_STANDARDS_FILE" ]; then
  f="$CONDUCTOR_STANDARDS_FILE"
elif [ -n "$CONDUCTOR_HOME" ]; then
  f="$CONDUCTOR_HOME/conductor/standards.md"
else
  exit 0
fi
s="$d/$sid"
if [ ! -f "$f" ]; then
  # No rules yet: remember this session saw none, so it gets the very first one when it is written.
  if [ ! -f "$s" ]; then
    mkdir -p "$d" 2>/dev/null && printf '{"last_id":0}' >"$s" 2>/dev/null && touch -t 200001010000 "$s" 2>/dev/null
  fi
  exit 0
fi
if [ -f "$s" ] && ! [ "$f" -nt "$s" ]; then exit 0; fi
CONDUCTOR_STANDARDS_FILE="$f" python3 -I "$root/scripts/standards" hook --event "$event" --state "$s" 2>/dev/null
exit 0
