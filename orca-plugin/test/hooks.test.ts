import { test } from 'node:test'
import assert from 'node:assert/strict'
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
  assert.deepEqual(out?.env, { CONDUCTOR_ROLE: 'worker', CONDUCTOR_HOME: '/srv/home-repo' })
})

test('launch with no role and no home repo passes unchanged', () => {
  assert.equal(decideLaunch(snap(), { agent: 'claude', workspaceId: 'w9', command: 'claude', env: {} }), null)
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
