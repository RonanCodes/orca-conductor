# Changelog

## 0.1.0 (2026-11-22)

First version. Not yet tried inside Orca.

- Orca plugin: roles, question gate, model by role, and a panel with the org chart, sleep and wake.
- Claude Code plugin: conductor and chief-of-staff skills, the `coordinator`, `standards`, `wiki`,
  `child-start`, `child-done` and `compact-check` scripts, a standards feed and a question gate.
- `child-start` starts a supervised worker in a child worktree with an explicit model alias, and tells it
  how to ask and how to hand back.
- A chat is identified by its session id and a terminal agent by its pane key. `compact-check` reads the
  transcript path the plugin's hook recorded.
- The scripts lock each read-modify-write in the home repo, so their own parallel writes are kept.
- One sleep and wake design, used by both plugins. Coordinators are never deleted.
- Not included: resuming agents after an account switch or usage limit. It needs Orca changes
  ([#44687](https://github.com/stablyai/orca/issues/44687),
  [#45251](https://github.com/stablyai/orca/issues/45251)).
