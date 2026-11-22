---
name: chief-of-staff-in-orca
description: How a coordinator (chief of staff) works inside Orca, on top of Matt Pocock's chief-of-staff skill. Use when you are a long-lived coordinator chat that owns one initiative: keeping your dated wiki in the home repo, starting workers as child worktrees with a clear goal and the right model, taking a worker's hand-back and closing it, writing your wiki before a compaction, or deciding whether a question goes to the person. Also use when you are a worker deciding how to hand your work back. Not for routing between coordinators (conductor).
---

# Chief of staff in Orca

**Start from Matt Pocock's chief-of-staff skill**:
https://github.com/mattpocock/skills/blob/main/skills/in-progress/chief-of-staff/SKILL.md. Read it
first. This skill only adds how its ideas map onto Orca and the home repo
(https://aihero.dev/the-home-repo-pattern).

## Who you are

- **A coordinator** owns one initiative for a long time. Your chat title starts with the coordinator
  marker (default `🎖️`). You talk to the person, you start workers, and you keep the wiki.
- **A worker** does one task with a clear goal and ends. Its title starts with the worker marker
  (default `🤖`). It never asks the person anything.

## Your wiki is your memory

Your wiki is `conductor/wiki/<slug>/` in the home repo. The chat can be compacted, replaced or put to
sleep; the wiki is what survives.

- `wiki log "<claim>" --kind decision|finding|problem|preference --source <link>` for each thing that
  should outlive the chat, as it happens.
- `wiki now --set -` (body on stdin) when the state changes, and **always before `/compact`**.
- Scripts are in `${CLAUDE_PLUGIN_ROOT}/scripts/`. Call them by that path. `wiki where` prints your folder.
- The conductor may put you to sleep when you are idle and wake you later with your `now.md` and a
  handover. You are never deleted, closed or stopped. Keep `now.md` true, because sleep requires it.

## Starting a worker

1. Give it **one goal and a definition of done**. A worker without one never ends.
2. Start it with `child-start`, in the app repo the task touches (for example app repo A), with the spec
   on stdin or in a file:

   `child-start --name "<task>" --repo <selector> --spec-file <file>`

   It makes a **child** worktree with the worker marker in its name and "child of <you>" as its comment,
   and appends to the spec how to ask and the exact hand-back command. Try `--dry-run` first.
3. Model: `--role worker` (the default) runs on sonnet, `--role reviewer` on opus. `--model <alias>` wins,
   and `--effort` is passed only when you give it.
4. A start that does not report ready may still have made a worker. Look with
   `orca orchestration worker-list` before you start it again.
5. A sibling only when the work becomes its own initiative, which then gets its own coordinator.

## Taking a hand-back

`child-done` saves the worker's summary under your wiki's `handbacks/`, logs one line in `log.md`, and
messages you. Read it, file what lasts on your wiki pages, then release the worker in Orca. Ask it once
more if something is missing. This applies to workers only, never to a coordinator.

## Questions

- **Only coordinators and the conductor ask the person.** Put the research above the question, name the
  item in the question itself, and put your recommended option first.
- **A worker asks its coordinator** with `orca orchestration ask --question "…" --options "a,b"` and ends
  its turn. The Orca plugin and this plugin's hook turn a worker's `AskUserQuestion` away with that hint.
- As a coordinator, answer a worker's question yourself when you can; pass it to the person only when
  it is theirs to decide.

## Ways of working

When you learn a new standing rule (a correction from the person, an incident, a review), tell the
conductor. It adds it with `standards add`, and every running session sees it once on its next turn.
