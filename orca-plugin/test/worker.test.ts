// The worker with a fake host, the real coordinator script and a fake orca CLI.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import activate from '../src/worker.ts'

test('the panel sleeps and wakes through the coordinator script, and roles reach the hooks', async () => {
  const home = mkdtempSync(join(tmpdir(), 'conductor-'))
  try {
    const wiki = join(home, 'conductor', 'wiki', 'docs')
    mkdirSync(wiki, { recursive: true })
    const chart = join(home, 'conductor', 'org-chart.md')
    writeFileSync(
      chart,
      '# Org chart\n\n| Coordinator | Owns | Wiki | Asleep/Awake | Session id |\n| --- | --- | --- | --- | --- |\n' +
        '| 🎖️ Docs | Handbook | `conductor/wiki/docs/` | 🟢 awake | `s-docs` |\n'
    )
    writeFileSync(join(wiki, 'now.md'), '# Docs: now\n\nChapter two is out.\n')
    const state = join(home, 'fake.json')
    writeFileSync(state, JSON.stringify({ agents: [], comment: 'keep this' }))
    process.env.CONDUCTOR_ORCA = fileURLToPath(new URL('../../claude-plugin/tests/fake_orca.py', import.meta.url))
    process.env.FAKE_ORCA_STATE = state

    const on = new Map<string, any>()
    const add = (kind: string) => (name: string, fn: any) => {
      on.set(`${kind}:${name}`, fn)
      return { dispose() {} }
    }
    const hostCalls: string[] = []
    const workspaces = [{ id: 'identity:abc', path: '/srv/app-a', name: 'app repo A' }]
    const settings = {
      homeRepoPath: home,
      coordinatorScript: fileURLToPath(new URL('../../claude-plugin/scripts/coordinator', import.meta.url))
    }
    await activate({
      hooks: { on: add('hook') },
      events: { on: add('event') },
      commands: { register: add('command') },
      panels: { handle: add('panel'), post() {} },
      settings: { get: async () => settings, onDidChange: () => ({ dispose() {} }) },
      storage: { get: async () => null, set: async () => {} },
      host: {
        call: async (method: string) => {
          hostCalls.push(method)
          return method === 'workspace.list'
            ? { workspaces }
            : { agents: [] }
        }
      },
      log() {}
    } as any)
    await new Promise((resolve) => setImmediate(resolve))

    on.get('event:workspace.changed')({
      context: { workspaceId: 'identity:abc', branch: 'main', displayName: 'app repo A', terminals: [] }
    })
    await on.get('command:role.worker')()
    const denied = on.get('hook:agent.tool.before')({
      agent: 'claude',
      workspaceId: 'repo::/srv/app-a',
      tool: 'AskUserQuestion'
    })
    assert.match(denied.deny, /worker/)

    // A new child: workspace.created has no name, so the worker reads it from workspace.list.
    workspaces.push({ id: 'identity:child', path: '/srv/fix-index', name: '🤖 fix-index' })
    const child = { workspaceId: 'repo::/srv/fix-index', workspaceListId: 'identity:child' }
    on.get('event:workspace.created')({ ...child, kind: 'worktree', path: '/srv/fix-index', branch: 'fix-index' })
    await new Promise((resolve) => setImmediate(resolve))
    const childDenied = on.get('hook:agent.tool.before')({
      agent: 'claude',
      workspaceId: child.workspaceId,
      tool: 'AskUserQuestion'
    })
    assert.match(childDenied?.deny ?? '', /worker/)

    const before = await on.get('panel:conductor.state')()
    assert.equal(before.org[0].asleep, false)
    const refused = await on.get('panel:conductor.sleep')({ session: 's-docs', owns: 'handbook', why: '', notes: 'docs' })
    assert.equal(refused.ok, false)

    const slept = await on.get('panel:conductor.sleep')({
      session: 's-docs',
      owns: 'handbook',
      why: 'shipped',
      notes: 'docs'
    })
    assert.equal(slept.ok, true, slept.lines.join('\n'))
    assert.match(readFileSync(chart, 'utf8'), /💤 asleep since/)
    assert.equal((await on.get('panel:conductor.state')()).org[0].asleep, true)

    const woke = await on.get('panel:conductor.wake')({ session: 's-docs', handover: 'chapter three' })
    assert.equal(woke.ok, true, woke.lines.join('\n'))
    const fake = JSON.parse(readFileSync(state, 'utf8'))
    assert.equal(fake.comment, 'keep this')
    assert.ok(fake.calls.at(-1).stdin.includes('chapter three'))
    assert.deepEqual([...new Set(hostCalls)].sort(), ['agents.list', 'workspace.list'])
  } finally {
    rmSync(home, { recursive: true, force: true })
  }
})
