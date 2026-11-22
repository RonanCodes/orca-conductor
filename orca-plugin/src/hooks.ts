// What the two hooks decide, from an in-memory snapshot only. Orca waits at most 2 s on a hook,
// and an awaited host call before the answer can time out and let the action through, so the
// worker keeps this snapshot current and the hooks never await.

import { applyPolicy, type Policy } from './policy.ts'
import { askDecision, resolveRole, roleFromTitle, type Markers, type Role } from './roles.ts'

export type Seen = { title: string | null; sessionId: string | null; workspaceId: string | null }

export type Snapshot = {
  markers: Markers
  askRoles: Role[]
  gateEnabled: boolean
  policy: Policy
  policyEnabled: boolean
  homeRepoPath: string
  /** Roles set by hand: `agent:<session or terminal id>` and `workspace:<id>`. */
  roles: Record<string, Role>
  /** What Orca last reported per terminal id. */
  terminals: Map<string, Seen>
  /** Orca's raw workspace id, as the hooks name it, to the id `workspace.list` gives. */
  workspaceIds: Map<string, string>
  /** A workspace path to its listed id, or null when two hosts share the path. */
  workspacePaths: Map<string, string | null>
}

/**
 * The listed id of a workspace. Hooks name a worktree `<repo id>::<path>`, while workspace.list and the
 * focused context name it `identity:...`, so roles set by hand are stored under the listed form.
 */
export function listedWorkspace(snap: Snapshot, id: string): string {
  const known = snap.workspaceIds.get(id)
  if (known) return known
  const at = id.indexOf('::')
  if (at === -1) return id
  return snap.workspacePaths.get(id.slice(at + 2)) ?? id
}

export type Resolved = { role: Role | null; source: 'agent' | 'title' | 'workspace' | null }

export function roleFor(
  snap: Snapshot,
  ids: { terminalId?: string | null; sessionId?: string | null; workspaceId?: string | null; title?: string | null }
): Resolved {
  const seen = ids.terminalId ? snap.terminals.get(ids.terminalId) : undefined
  const sessionId = ids.sessionId ?? seen?.sessionId ?? null
  const named = ids.workspaceId ?? seen?.workspaceId ?? null
  const workspaceId = named ? listedWorkspace(snap, named) : null
  const agent =
    (sessionId ? snap.roles[`agent:${sessionId}`] : undefined) ??
    (ids.terminalId ? snap.roles[`agent:${ids.terminalId}`] : undefined) ??
    null
  const title = roleFromTitle(ids.title ?? seen?.title ?? null, snap.markers)
  const workspace = workspaceId ? (snap.roles[`workspace:${workspaceId}`] ?? null) : null
  const role = resolveRole({ agent, title, workspace })
  const source = role === null ? null : agent ? 'agent' : title ? 'title' : 'workspace'
  return { role, source }
}

export const ASK_TOOLS = new Set(['AskUserQuestion'])

export type ToolEvent = { agent: string; workspaceId: string | null; terminalId?: string; tool: string }

/** `{ deny }` for an AskUserQuestion from a role that may not ask, else undefined (pass). */
export function decideTool(snap: Snapshot, event: ToolEvent): { deny: string } | undefined {
  if (!snap.gateEnabled || !ASK_TOOLS.has(event.tool)) return undefined
  const { role } = roleFor(snap, { terminalId: event.terminalId, workspaceId: event.workspaceId })
  const reason = askDecision(role, snap.askRoles)
  // Orca refuses a deny reason over 500 characters, and a refused answer lets the call through.
  return reason ? { deny: reason.slice(0, 500) } : undefined
}

export type LaunchEvent = {
  agent: string
  workspaceId: string | null
  terminalId?: string
  command: string
  env: Record<string, string>
}

/** The launch event with the role's model policy and the role variables applied, or null to pass. */
export function decideLaunch(snap: Snapshot, event: LaunchEvent): LaunchEvent | null {
  const { role } = roleFor(snap, { terminalId: event.terminalId, workspaceId: event.workspaceId })
  const env: Record<string, string> = { ...event.env }
  if (role) env.CONDUCTOR_ROLE = role
  if (snap.homeRepoPath.trim() !== '') env.CONDUCTOR_HOME = snap.homeRepoPath.trim()
  const command =
    snap.policyEnabled && event.agent === 'claude' ? applyPolicy(event.command, role, snap.policy) : event.command
  const changed = command !== event.command || Object.keys(env).length !== Object.keys(event.env).length
  return changed ? { ...event, command, env } : null
}
