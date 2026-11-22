import { test } from 'node:test'
import assert from 'node:assert/strict'
import { applyPolicy, isAlias, parsePolicy } from '../src/policy.ts'

test('parses the default policy', () => {
  const { policy, errors } = parsePolicy(undefined)
  assert.deepEqual(errors, [])
  assert.deepEqual(policy.worker, { model: 'sonnet', effort: 'medium' })
  assert.deepEqual(policy.coordinator, { model: 'opus', effort: 'high' })
})

test('refuses pinned model ids, unknown roles and efforts, keeps the good entries', () => {
  const { policy, errors } = parsePolicy('worker=claude-sonnet-4-5; reviewer=opus; coordinator=opus:huge; conductor=fable')
  assert.equal(errors.length, 3)
  assert.deepEqual(policy, { conductor: { model: 'fable' } })
  assert.equal(isAlias('opus'), true)
  assert.equal(isAlias('sonnet-4'), false)
})

test('adds model and effort after the claude executable', () => {
  const { policy } = parsePolicy(undefined)
  assert.equal(applyPolicy('claude', 'worker', policy), 'claude --model sonnet --effort medium')
  assert.equal(
    applyPolicy("cd /repo && /opt/bin/claude 'fix it'", 'coordinator', policy),
    "cd /repo && /opt/bin/claude --model opus --effort high 'fix it'"
  )
})

test('never overrides an explicit --model or --effort', () => {
  const { policy } = parsePolicy(undefined)
  assert.equal(applyPolicy('claude --model opus', 'worker', policy), 'claude --effort medium --model opus')
  assert.equal(applyPolicy('claude --model=haiku --effort low', 'worker', policy), 'claude --model=haiku --effort low')
})

test('leaves the command alone without a role, an entry or a claude word', () => {
  const { policy } = parsePolicy('worker=sonnet')
  assert.equal(applyPolicy('claude', null, policy), 'claude')
  assert.equal(applyPolicy('claude', 'coordinator', policy), 'claude')
  assert.equal(applyPolicy('codex', 'worker', policy), 'codex')
  assert.equal(applyPolicy('claudette', 'worker', policy), 'claudette')
})

test('a resumed session keeps its model', () => {
  const { policy } = parsePolicy('worker=sonnet:medium')
  const resumes = ['--resume abc', '--resume=abc', '--resume', '-r abc', '-rabc', '--continue', '-c', '-pc', '--from-pr 12', '--teleport']
  for (const flags of resumes) {
    assert.equal(applyPolicy(`claude ${flags}`, 'worker', policy), `claude ${flags}`, flags)
  }
  assert.notEqual(applyPolicy("claude 'continue with -c please'", 'worker', policy), "claude 'continue with -c please'")
})

test('never edits a prompt or a folder that says claude', () => {
  const { policy } = parsePolicy('worker=sonnet')
  for (const command of ["myagent 'ask claude now'", 'echo claude', "run 'use claude here", 'cd /x/claude']) {
    assert.equal(applyPolicy(command, 'worker', policy), command)
  }
  assert.equal(applyPolicy('cd /x/claude && claude', 'worker', policy), 'cd /x/claude && claude --model sonnet')
  assert.equal(applyPolicy("A=1 '/opt/my tools/claude'", 'worker', policy), "A=1 '/opt/my tools/claude' --model sonnet")
})

test('a prompt that mentions --model is not an explicit --model, a quoted flag is', () => {
  const { policy } = parsePolicy('worker=sonnet')
  assert.equal(applyPolicy("claude '--model is broken'", 'worker', policy), "claude --model sonnet '--model is broken'")
  assert.equal(applyPolicy("claude '--model' 'opus'", 'worker', policy), "claude '--model' 'opus'")
})
