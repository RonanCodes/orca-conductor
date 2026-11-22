# Conductor for Orca

**Run [Orca](https://github.com/stablyai/orca) as one conductor over a few long-lived chiefs of staff, each with its own short-lived workers.**

Two plugins in one repo, built on what Orca offers today. They are a stopgap for what
[stablyai/orca#46872](https://github.com/stablyai/orca/issues/46872) asks Orca to support itself.

> **Status: 0.1.0, not yet tried inside Orca.** The unit tests and validators pass. Neither plugin has been
> installed or run against live chats. See [What is unverified](#what-is-unverified) before you rely on it.

## The setup

| Role | Default title marker | How long it lives | What it does | May ask you? |
| --- | --- | --- | --- | --- |
| Conductor | 🎩 | always | routes requests, keeps the org chart, adds standing rules | yes |
| Coordinator (chief of staff) | 🎖️ | one per initiative, never deleted | owns a topic and its wiki, starts workers | yes |
| Worker | 🤖 | one task | does the task, hands back, is released by its coordinator | no, it asks its coordinator |

An idle coordinator is marked asleep with a note and woken later. Nothing here deletes, closes or stops one.

Everything that must outlive a chat is in a **home repo**, one git repo that is yours. App repo A and app
repo B stay free of it.

```text
home repo/
  conductor/
    org-chart.md          every coordinator: what it owns, wiki, awake or asleep, session id
    standards.md          numbered standing rules
    wiki/<coordinator>/   index.md, now.md, log.md, handbacks/
```

## Install

You need macOS or Linux, Orca 1.4.260 or newer, Claude Code, `python3` 3.9 or newer, and the `orca` CLI on
your `PATH`.

1. Clone this repo, and make or pick a home repo.

   ```sh
   git clone https://github.com/RonanCodes/orca-conductor
   mkdir -p /path/to/home-repo/conductor
   ```

2. Install the Claude Code plugin.

   ```text
   /plugin marketplace add RonanCodes/orca-conductor
   /plugin install orca-conductor@orca-conductor
   ```

3. Tell Claude Code where the home repo is, in the `env` block of its user `settings.json`.

   ```json
   { "env": { "CONDUCTOR_HOME": "/path/to/home-repo" } }
   ```

4. Install the Orca plugin from the clone. Orca prints what it would grant and the command to approve it.

   ```sh
   orca plugin install "$PWD/orca-conductor/orca-plugin"
   ```

5. In Orca's Settings, Plugins, Conductor, set **Home repo folder** to the home repo and **Coordinator
   script** to the clone's `claude-plugin/scripts/coordinator` (absolute paths).

Then start a chat in the home repo, title it `🎩 Conductor` and ask it to use the `conductor` skill.

<details>
<summary>Why the Orca plugin installs from a folder</summary>

Orca reads a plugin's manifest from the root of a Git repo, or from a catalog entry's `source.path`. This repo
holds two plugins, so until it is in a catalog you install the `orca-plugin` folder. A folder install gets the
id `local.conductor`. Its settings point at the script in the Claude Code plugin, so there is one sleep and
wake implementation and not two.
</details>

<details>
<summary>Use either plugin alone</summary>

- **Claude Code plugin alone:** skills, scripts, standards feed and a question gate. No panel and no model
  policy.
- **Orca plugin alone:** roles, question gate and model by role. The org chart, sleep and wake need the script
  from this repo's `claude-plugin` folder and `python3`.
</details>

## What each feature uses from Orca today

| Feature | Part | What it uses |
| --- | --- | --- |
| Roles, from a title marker or a palette command | Orca plugin | `storage:own`, `workspace.list`, `agents.list`, workspace events |
| Question gate on `AskUserQuestion` | both | hook `agent.tool.before`; in Claude Code a `PreToolUse` hook |
| Model and effort by role | Orca plugin | hook `agent.launch.before`; an explicit `--model` or `--effort` wins |
| Org chart panel | Orca plugin | a components panel, the `coordinator` script |
| Sleep and wake, as marks | both | `orca worktree show` and `set --comment`, `orca agent list`, `orca terminal list`, `orca orchestration send` |
| Standards every session sees once | Claude Code plugin | no Orca API: a file and Claude Code hooks |
| Dated wiki per coordinator | Claude Code plugin | no Orca API: files in the home repo |
| Worker hand-back | Claude Code plugin | `orca orchestration send` |
| Compaction check | Claude Code plugin | `orca agent list`, Claude Code transcripts of terminal agents |

<details>
<summary>The scripts</summary>

They are in `claude-plugin/scripts/`. Each has `--help`.

| Script | Commands |
| --- | --- |
| `coordinator` | `ls`, `check`, `new`, `sleep`, `wake` |
| `standards` | `add`, `ls`, `since`, `show`, `path` |
| `wiki` | `where`, `init`, `log`, `now` |
| `child-done` | `--parent <coordinator>`, summary on stdin or in `--summary-file` |
| `compact-check` | a dry run; `--ask-wiki` asks each due coordinator to write its wiki |

`coordinator new` registers a chat you started. It starts none itself. It refuses with exit 3 when a sleeping
coordinator fits, unless you add `--force-new`.
</details>

<details>
<summary>How sleep and wake behave</summary>

- **Sleep** needs a note (what it owns, why it sleeps, where its notes live) and a `now.md` with a real
  summary written in the last hour. An older one is accepted only when the coordinator is idle. Sleep adds a
  💤 segment to the worktree comment and marks the org chart.
- **Wake** clears both and sends the coordinator the path of its `now.md` and your handover. A chat is
  addressed by its session id and a terminal agent by its terminal handle. A sleeping terminal agent cannot be
  messaged, so reopen its workspace first.
- **Neither touches the tab, worktree or process.** Orca has no sleep or wake API yet. The sidebar's Sleep
  acts on a whole workspace, so use it only for a coordinator that has the workspace to itself.
- `coordinator check` and `compact-check` skip sleepers.
- A delete, archive, remove, close, kill or stop subcommand exits 2.

In the Orca panel sleep and wake are forms, because a palette command cannot take the required note.
</details>

<details>
<summary>Settings and environment variables</summary>

The Orca plugin's settings are the gate switch, the roles that may ask, the model policy
(`role=alias:effort`, aliases only), the three markers, the home repo folder and the coordinator script.

| Variable | What it does |
| --- | --- |
| `CONDUCTOR_HOME` | the home repo |
| `CONDUCTOR_STANDARDS_FILE` | a standards file somewhere else |
| `CONDUCTOR_ORG_CHART` | an org chart somewhere else |
| `CONDUCTOR_MARKERS` | `conductor=🎩,coordinator=🎖️,worker=🤖` |
| `CONDUCTOR_ROLE` | this session's role when its title has no marker |
| `CONDUCTOR_ASK_ROLES` | roles that may ask, default `conductor,coordinator` |
| `CONDUCTOR_COORDINATOR` | which wiki the `wiki` script writes |
| `CONDUCTOR_CHILD_NAME` | a worker's name in its hand-back |
| `CONDUCTOR_STANDARDS_CAP` | characters of rules injected per turn, default 1500 |
| `CONDUCTOR_STATE_DIR` | where the once-per-session state lives |
| `CONDUCTOR_ORCA` | the `orca` executable |
</details>

<details>
<summary>What it can access</summary>

- The Orca plugin is a trusted worker, so it runs with your user account's access. It asks for
  `storage:own`, `settings:own`, `workspace:read` and `agent:read`, and runs one program: `python3` with the
  coordinator script you set.
- The scripts run five Orca commands and refuse all others: `agent list`, `terminal list`, `worktree show`,
  `worktree set` and `orchestration send`.
- The standards hook reads rules only from the home repo or file you configured, never from whichever repo a
  session is in, because that repo may not be yours.
- `compact-check` reads token counts from local transcripts. Nothing here makes a network call of its own.
</details>

## What is unverified

- **Native chats:** whether Orca's `agent.tool.before` and Claude Code plugin hooks fire in them.
- **SSH and WSL:** Orca does not run `agent.tool.before` there.
- **The plugin worker's `PATH`:** whether `python3` and `orca` are found from a real worker.
- **Model by role in real launches.** Orca runs that hook for agent terminals only, not for restores or
  resumes, and a brand-new child workspace usually has no role yet, so set one first.
- **Title markers** when the agent's program replaces the tab title. Set the role by command in that case.
- **Messages:** delivery to real and sleeping agents, and ambiguous recipients
  ([#45666](https://github.com/stablyai/orca/issues/45666)). `sent` means Orca took the message, not that the
  agent read it.
- **`orca orchestration ask` outside a Run:** it has no coordinator to reach, so the gate also tells the
  worker to use `send`.
- **The panel inside Orca, and a live sleep and wake.** The panel was only rendered by `orca plugin check`,
  and sleep and wake only ran against a fake CLI.
- **Windows:** not supported (the scripts use `fcntl` and POSIX quoting).

## Needs upstream / not yet working

- **Resume all after an account switch or usage limit: not included, and not working.** Orca's documented
  plugin API cannot do it on its own. `agent.resume` opens a terminal, so a native chat cannot come back as a
  chat. The session list calls an agent that stopped on a limit but is still open running, so it would be
  skipped. No API moves an agent to the new account. That comes from reading Orca's source and was not tried
  live. Resume each agent yourself. See [#44687](https://github.com/stablyai/orca/issues/44687) and
  [#45251](https://github.com/stablyai/orca/issues/45251).
- **Roles as real metadata, and a question gate in Orca:** [#46873](https://github.com/stablyai/orca/issues/46873).
  Titles and workspace roles stand in here.
- **Model policy by role:** [#46874](https://github.com/stablyai/orca/issues/46874).
- **Create, sleep, wake and compact from a documented CLI or API:**
  [#46875](https://github.com/stablyai/orca/issues/46875). Sleep and wake here are marks, and the compaction
  check only tells you where to type `/compact`. It cannot count a native chat's tokens.
- **Hand back, then close the child:** [#46876](https://github.com/stablyai/orca/issues/46876). `child-done`
  only hands back.
- **Broadcast to every session:** [#43757](https://github.com/stablyai/orca/issues/43757). The standards hook
  reaches only Claude Code sessions, at their next prompt or tool call.
- **A nested coordinator a Run can escalate to:** [#13362](https://github.com/stablyai/orca/issues/13362).
- **The whole setup:** [#46872](https://github.com/stablyai/orca/issues/46872).

## Develop

```sh
cd orca-plugin
node --test test/*.test.ts
orca plugin types . && tsc -p .
orca plugin validate . && orca plugin check .
cd ..
python3 -m unittest discover -s claude-plugin/tests
claude plugin validate .
```

Tested with Node 24.19, Python 3.9 and 3.14, and the validators of Orca 1.4.266 and Claude Code 2.1.330.
The tests use a fake `orca` and never touch live chats.

## Credits

- **[Matt Pocock](https://github.com/mattpocock)** for the
  [chief-of-staff skill](https://github.com/mattpocock/skills/blob/main/skills/in-progress/chief-of-staff/SKILL.md),
  the base of the coordinator role, and the
  [home repo pattern](https://aihero.dev/the-home-repo-pattern). The skill is linked, not copied.
- Prior art among [Orca's community plugins](https://github.com/stablyai/orca-community-plugins):
  [Agent Profiles](https://onorca.dev/plugins/erom.agent-profiles?catalog=community) by erom,
  [Auto Hand-off](https://onorca.dev/plugins/ngoohebi.auto-handoff?catalog=community) by ngoohebi,
  [Chat Board](https://onorca.dev/plugins/santiagocaprile.chat-board?catalog=community) by santiagocaprile and
  [Agent Inbox](https://onorca.dev/plugins/anthony-fp.agent-inbox?catalog=community) by anthony-fp.

[Changelog](CHANGELOG.md) · [MIT licence](LICENSE)
