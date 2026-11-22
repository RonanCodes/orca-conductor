// Calls the `coordinator` script from the Claude Code plugin. That script holds the one sleep and wake
// design, so this plugin has no copy of it: it never writes the org chart or a worktree comment itself.
// Never through a shell: arguments go as an argv. Nothing here closes, stops or signals a process.

import { spawn } from 'node:child_process'
import type { Markers } from './roles.ts'

export type ScriptSetup = { script: string; home: string; markers: Markers }
export type ScriptResult = { ok: boolean; stdout: string; output: string }

const WAIT_MS = 85_000
const OUTPUT_MAX = 512 * 1024

/** What is missing before the script can run, or null. */
export function setupProblem(setup: ScriptSetup): string | null {
  const missing = [
    setup.home === '' ? '"Home repo folder"' : null,
    setup.script === '' ? '"Coordinator script"' : null
  ].filter((item): item is string => item !== null)
  if (missing.length === 0) return null
  return `Set ${missing.join(' and ')} in Settings, Plugins, Conductor. The script ships in the Claude Code plugin at scripts/coordinator.`
}

export function sleepNote(parts: { owns: string; why: string; notes: string }): { note: string } | { error: string } {
  const owns = parts.owns.trim()
  const why = parts.why.trim()
  const notes = parts.notes.trim()
  const missing = [
    owns === '' ? 'what it owns' : null,
    why === '' ? 'why it sleeps' : null,
    notes === '' ? 'where its notes live' : null
  ].filter((item): item is string => item !== null)
  if (missing.length > 0) return { error: `A sleep note needs ${missing.join(', ')}.` }
  return { note: `${owns}; ${why}; ${notes}` }
}

export function runCoordinator(setup: ScriptSetup, args: readonly string[], stdin = ''): Promise<ScriptResult> {
  const problem = setupProblem(setup)
  if (problem) return Promise.resolve({ ok: false, stdout: '', output: problem })
  return new Promise((resolve) => {
    let stdout = ''
    let stderr = ''
    let settled = false
    const finish = (ok: boolean, failure?: string) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve({ ok, stdout, output: (failure ?? `${stdout}${stderr}`).trim() })
    }
    const timer = setTimeout(
      () => finish(false, 'The coordinator script has not answered yet. Check the org chart before trying again.'),
      WAIT_MS
    )
    const env = {
      ...process.env,
      CONDUCTOR_HOME: setup.home,
      CONDUCTOR_MARKERS: Object.entries(setup.markers)
        .map(([role, marker]) => `${role}=${marker}`)
        .join(',')
    }
    const child = spawn('python3', [setup.script, ...args], { stdio: ['pipe', 'pipe', 'pipe'], env })
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (chunk) => {
      if (stdout.length < OUTPUT_MAX) stdout += chunk
    })
    child.stderr.on('data', (chunk) => {
      if (stderr.length < OUTPUT_MAX) stderr += chunk
    })
    child.on('error', (error) => finish(false, `python3 did not start (${error.message})`))
    child.on('close', (code) => finish(code === 0))
    // A script that exits before it reads stdin makes this pipe fail; the exit code already says so.
    child.stdin.on('error', () => {})
    child.stdin.end(stdin)
  })
}
