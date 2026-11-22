import { test } from 'node:test'
import assert from 'node:assert/strict'
import { askDecision, parseAskRoles, readMarkers, resolveRole, roleFromTitle } from '../src/roles.ts'

test('derives the role from a title prefix', () => {
  assert.equal(roleFromTitle('🎖️ 🧪 Testing'), 'coordinator')
  assert.equal(roleFromTitle('🤖 fix the flaky test'), 'worker')
  assert.equal(roleFromTitle('  🎩 🎖️🎖️ Conductor'), 'conductor')
  assert.equal(roleFromTitle('Plain title'), null)
  assert.equal(roleFromTitle(null), null)
})

test('the conductor wins over the coordinator marker it also carries', () => {
  assert.equal(roleFromTitle('🎩 🎖️🎖️ Conductor'), 'conductor')
})

test('matches with or without the emoji variation selector', () => {
  assert.equal(roleFromTitle('🎖 Initiative'), 'coordinator')
  assert.equal(roleFromTitle('🎖️ Initiative', readMarkers({ markerCoordinator: '🎖' })), 'coordinator')
})

test('custom markers replace the defaults; empty keeps them', () => {
  const markers = readMarkers({ markerCoordinator: '[C]', markerWorker: '' })
  assert.equal(roleFromTitle('[C] app repo A', markers), 'coordinator')
  assert.equal(roleFromTitle('🤖 task', markers), 'worker')
  assert.equal(roleFromTitle('🎖️ old marker', markers), null)
})

test('a role set by hand beats the title, which beats the workspace', () => {
  assert.equal(resolveRole({ agent: 'worker', title: 'coordinator', workspace: 'conductor' }), 'worker')
  assert.equal(resolveRole({ title: 'coordinator', workspace: 'worker' }), 'coordinator')
  assert.equal(resolveRole({ workspace: 'worker' }), 'worker')
  assert.equal(resolveRole({}), null)
})

test('ask roles parse from text and default to conductor and coordinator', () => {
  assert.deepEqual(parseAskRoles(''), ['conductor', 'coordinator'])
  assert.deepEqual(parseAskRoles('coordinator, nobody'), ['coordinator'])
})

test('only roles outside the ask list are turned away', () => {
  const ask = parseAskRoles(undefined)
  assert.equal(askDecision('coordinator', ask), null)
  assert.equal(askDecision(null, ask), null)
  const reason = askDecision('worker', ask)
  assert.ok(reason && reason.includes('orca orchestration ask'))
})
