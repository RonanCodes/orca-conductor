import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { decideLaunch, decideTool, type Snapshot } from '../src/hooks.ts'
import { parsePolicy } from '../src/policy.ts'
import { DEFAULT_MARKERS } from '../src/roles.ts'

function snap(over: Partial<Snapshot> = {}): Snapshot {
  return {
    markers: DEFAULT_MARKERS,
    askRoles: ['conductor', 'coordinator'],
    gateEnabled: true,
    policy: parsePolicy(undefined).policy,
    policyEnabled: true,
    homeRepoPath: '',
    roles: {},
    terminals: new Map(),
    workspaceIds: new Map(),
    workspacePaths: new Map(),
    workspaceNames: new Map(),
    ...over
  }
}

test('denies AskUserQuestion from a worker found by its title', () => {
  const s = snap({ terminals: new Map([['t1', { title: '🤖 task', sessionId: 's1', workspaceId: 'w1' }]]) })
  const result = decideTool(s, { agent: 'claude', workspaceId: 'w1', terminalId: 't1', tool: 'AskUserQuestion' })
  assert.ok(result?.deny.includes('worker'))
})

test('passes coordinators, unknown agents, other tools, and everything when the gate is off', () => {
  const terminals = new Map([['t1', { title: '🎖️ initiative', sessionId: 's1', workspaceId: 'w1' }]])
  assert.equal(decideTool(snap({ terminals }), { agent: 'claude', workspaceId: 'w1', terminalId: 't1', tool: 'AskUserQuestion' }), undefined)
  assert.equal(decideTool(snap(), { agent: 'claude', workspaceId: null, tool: 'AskUserQuestion' }), undefined)
  const worker = snap({ roles: { 'workspace:w1': 'worker' } })
  assert.equal(decideTool(worker, { agent: 'claude', workspaceId: 'w1', tool: 'Bash' }), undefined)
  assert.equal(decideTool({ ...worker, gateEnabled: false }, { agent: 'claude', workspaceId: 'w1', tool: 'AskUserQuestion' }), undefined)
})

test('a role set by hand on the session beats the title', () => {
  const s = snap({
    roles: { 'agent:s1': 'coordinator' },
    terminals: new Map([['t1', { title: '🤖 promoted', sessionId: 's1', workspaceId: 'w1' }]])
  })
  assert.equal(decideTool(s, { agent: 'claude', workspaceId: 'w1', terminalId: 't1', tool: 'AskUserQuestion' }), undefined)
})

test('launch in a worker workspace gets the worker model and the role variables', () => {
  const s = snap({ roles: { 'workspace:w2': 'worker' }, homeRepoPath: '/srv/home-repo' })
  const out = decideLaunch(s, { agent: 'claude', workspaceId: 'w2', command: 'claude', env: {} })
  assert.equal(out?.command, 'claude --model sonnet --effort medium')
  assert.equal(out?.env.CONDUCTOR_ROLE, 'worker')
  assert.equal(out?.env.CONDUCTOR_ROLE_SOURCE, 'workspace')
  assert.equal(out?.env.CONDUCTOR_HOME, '/srv/home-repo')
})

test('another agent with no role and no home repo passes unchanged', () => {
  assert.equal(decideLaunch(snap(), { agent: 'codex', workspaceId: 'w9', command: 'codex', env: {} }), null)
})

test('a stale value in the launch env is overwritten, not kept', () => {
  const s = snap({ roles: { 'workspace:w': 'worker' }, policyEnabled: false, homeRepoPath: '/srv/home-repo' })
  const first = decideLaunch(s, { agent: 'claude', workspaceId: 'w', command: 'claude', env: {} })!
  assert.equal(decideLaunch(s, { ...first }), null, 'equal values pass unchanged')
  for (const key of ['CONDUCTOR_ROLE', 'CONDUCTOR_HOME']) {
    const out = decideLaunch(s, { ...first, env: { ...first.env, [key]: 'coordinator' } })
    assert.equal(out?.env[key], first.env[key], key)
  }
})

test('the reviewed case: a worker launched with CONDUCTOR_ROLE=coordinator', () => {
  const s = snap({ roles: { 'workspace:w': 'worker' }, policyEnabled: false })
  const event = { agent: 'codex', workspaceId: 'w', command: 'codex', env: { CONDUCTOR_ROLE: 'coordinator' } }
  assert.equal(decideLaunch(s, event)?.env.CONDUCTOR_ROLE, 'worker')
})

test('the Orca settings reach the Claude hook in the launch env', () => {
  const markers = { conductor: '[top]', coordinator: '[c]', worker: '[w,=]' }
  const s = snap({ markers, gateEnabled: false, askRoles: [], policyEnabled: false })
  const env = decideLaunch(s, { agent: 'claude', workspaceId: 'w9', command: 'claude', env: {} })?.env
  assert.equal(env?.CONDUCTOR_GATE, 'off')
  assert.equal(env?.CONDUCTOR_ASK_ROLES, 'none')
  assert.deepEqual(JSON.parse(env?.CONDUCTOR_MARKERS ?? '{}'), markers)
})

test('both gates agree on the env this plugin sends', () => {
  const gate = fileURLToPath(new URL('../../claude-plugin/hooks/ask_gate.py', import.meta.url))
  const clean = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(ORCA_|CONDUCTOR_)/.test(key)))
  const titled = new Map([['t1', { title: '🤖 promoted', sessionId: null, workspaceId: 'w' }]])
  const worker = { 'workspace:w': 'worker' as const }
  const cases = [
    snap({ roles: worker }),
    snap({ roles: worker, gateEnabled: false }),
    snap({ roles: worker, askRoles: ['worker'] }),
    snap({ roles: worker, askRoles: [] }),
    snap({ roles: { ...worker, 'agent:t1': 'coordinator' }, terminals: titled })
  ]
  for (const [index, s] of cases.entries()) {
    const at = { agent: 'claude', workspaceId: 'w', terminalId: 't1' }
    const env = decideLaunch(s, { ...at, command: 'claude', env: {} })?.env ?? {}
    const hook = spawnSync('python3', [gate], {
      input: JSON.stringify({ tool_name: 'AskUserQuestion' }),
      env: { ...clean, ...env, CONDUCTOR_ORCA: '/nonexistent-orca' },
      encoding: 'utf8'
    })
    const orcaDenies = decideTool(s, { ...at, tool: 'AskUserQuestion' }) !== undefined
    assert.equal(hook.stdout.includes('"deny"'), orcaDenies, `case ${index}`)
  }
})

test('a role set by hand is named as the source at launch', () => {
  const s = snap({
    roles: { 'agent:t1': 'coordinator' },
    terminals: new Map([['t1', { title: '🤖 promoted', sessionId: null, workspaceId: 'w' }]])
  })
  const env = decideLaunch(s, { agent: 'claude', workspaceId: 'w', terminalId: 't1', command: 'claude', env: {} })?.env
  assert.equal(env?.CONDUCTOR_ROLE, 'coordinator')
  assert.equal(env?.CONDUCTOR_ROLE_SOURCE, 'agent')
})

test('a worker marker on the workspace name makes a worker, a coordinator marker makes nothing', () => {
  const event = { agent: 'claude', workspaceId: 'w', tool: 'AskUserQuestion' }
  assert.ok(decideTool(snap({ workspaceNames: new Map([['w', '🤖 fix-index']]) }), event))
  const other = snap({ workspaceNames: new Map([['w', '🎖️ Search']]), askRoles: ['conductor'] })
  assert.equal(decideTool(other, event), undefined)
})

test('a role set on the listed workspace id applies to the raw id the hooks send', () => {
  const roles = { 'workspace:identity:abc': 'worker' as const }
  const event = { agent: 'claude', workspaceId: 'repo-1::/srv/app-a', tool: 'AskUserQuestion' }
  assert.ok(decideTool(snap({ roles, workspacePaths: new Map([['/srv/app-a', 'identity:abc']]) }), event))
  assert.ok(decideTool(snap({ roles, workspaceIds: new Map([['repo-1::/srv/app-a', 'identity:abc']]) }), event))
  assert.equal(decideTool(snap({ roles, workspacePaths: new Map([['/srv/app-a', null]]) }), event), undefined)
})

test('a deny reason fits the 500 characters Orca takes', () => {
  const s = snap({ roles: { 'workspace:w': 'worker' }, askRoles: Array(60).fill('coordinator') })
  const result = decideTool(s, { agent: 'claude', workspaceId: 'w', tool: 'AskUserQuestion' })
  assert.ok(result && result.deny.length <= 500)
})
