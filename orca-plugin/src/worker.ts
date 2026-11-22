// The plugin's worker: keeps roles in orca.storage, answers the question gate and the model policy
// hooks from memory, and hands the org chart, sleep and wake to the `coordinator` script.
// Orca transpiles this file; no build step.
import type { OrcaWorkerApi } from 'orca/worker'
import { runCoordinator, sleepNote, type ScriptSetup } from './cli.ts'
import { decideLaunch, decideTool, listedWorkspace, roleFor, type Snapshot } from './hooks.ts'
import { parsePolicy } from './policy.ts'
import type { AgentRow, OrgEntry, PanelState, StepReport } from './protocol.ts'
import { DEFAULT_MARKERS, isRole, parseAskRoles, readMarkers, type Role } from './roles.ts'

const ROLES_KEY = 'roles'

export default async function activate(orca: OrcaWorkerApi): Promise<void> {
  const snap: Snapshot = {
    markers: DEFAULT_MARKERS,
    askRoles: parseAskRoles(undefined),
    gateEnabled: true,
    policy: parsePolicy(undefined).policy,
    policyEnabled: true,
    homeRepoPath: '',
    roles: {},
    terminals: new Map(),
    workspaceIds: new Map(),
    workspacePaths: new Map()
  }
  let policyWarnings: string[] = []
  let script = ''
  let focused: { id: string | null; name: string } | null = null

  // The hooks first, answered from the snapshot only: never an awaited call before the answer.
  orca.hooks.on('agent.tool.before', (event) => decideTool(snap, event))
  orca.hooks.on('agent.launch.before', (event, next) => {
    const changed = decideLaunch(snap, event)
    return changed ? next({ ...event, command: changed.command, env: changed.env }) : next(event)
  })

  async function loadSettings(): Promise<void> {
    let values: Record<string, unknown> = {}
    try {
      values = await orca.settings.get()
    } catch (error) {
      orca.log(`settings not read: ${(error as Error).message}`)
    }
    snap.markers = readMarkers(values)
    snap.askRoles = parseAskRoles(values.askRoles)
    snap.gateEnabled = values.gateEnabled !== false
    const parsed = parsePolicy(values.modelPolicy)
    snap.policy = parsed.policy
    policyWarnings = parsed.errors.map((error) => `Model policy: ${error}`)
    snap.policyEnabled = values.modelPolicyEnabled !== false
    snap.homeRepoPath = typeof values.homeRepoPath === 'string' ? values.homeRepoPath.trim() : ''
    script = typeof values.coordinatorScript === 'string' ? values.coordinatorScript.trim() : ''
  }

  async function loadRoles(): Promise<void> {
    const stored = await orca.storage.get(ROLES_KEY)
    if (!stored || typeof stored !== 'object') return
    for (const [key, value] of Object.entries(stored as Record<string, unknown>)) {
      if (isRole(value)) snap.roles[key] = value
    }
  }

  function remember(
    terminalId: string | null | undefined,
    seen: { title?: string | null; sessionId?: string | null; workspaceId?: string | null }
  ): void {
    if (!terminalId) return
    const before = snap.terminals.get(terminalId)
    snap.terminals.set(terminalId, {
      title: seen.title ?? before?.title ?? null,
      sessionId: seen.sessionId ?? before?.sessionId ?? null,
      workspaceId: seen.workspaceId ?? before?.workspaceId ?? null
    })
  }

  async function agentsIn(workspaceId: string) {
    try {
      return (await orca.host.call('agents.list', { workspaceId })).agents
    } catch {
      return []
    }
  }

  /** Learns every workspace's id and path and each agent's title, for the hooks. */
  async function scanAll(): Promise<void> {
    try {
      const { workspaces } = await orca.host.call('workspace.list', {})
      for (const ws of workspaces) {
        // One path on two hosts is ambiguous, so it names no workspace.
        const known = snap.workspacePaths.get(ws.path)
        snap.workspacePaths.set(ws.path, known === undefined || known === ws.id ? ws.id : null)
      }
      for (const ws of workspaces) {
        for (const row of await agentsIn(ws.id)) {
          remember(row.terminalId, { title: row.title, sessionId: row.sessionId, workspaceId: ws.id })
        }
      }
    } catch (error) {
      orca.log(`scan failed: ${(error as Error).message}`)
    }
  }

  const setup = (): ScriptSetup => ({ script, home: snap.homeRepoPath, markers: snap.markers })

  async function orgChart(): Promise<{ rows: OrgEntry[]; warnings: string[] }> {
    const result = await runCoordinator(setup(), ['ls', '--json'])
    if (!result.ok) return { rows: [], warnings: [result.output || 'The coordinator script failed.'] }
    try {
      const parsed = JSON.parse(result.stdout) as { rows: OrgEntry[]; warning: string | null }
      return { rows: parsed.rows, warnings: parsed.warning ? [`No live state: ${parsed.warning}`] : [] }
    } catch {
      return { rows: [], warnings: ['The coordinator script printed something this panel cannot read.'] }
    }
  }

  async function panelState(): Promise<PanelState> {
    const at = focused
    const agents: AgentRow[] = []
    if (at?.id) {
      for (const row of await agentsIn(at.id)) {
        const key = row.sessionId ?? row.terminalId
        if (!key) continue
        remember(row.terminalId, { title: row.title, sessionId: row.sessionId, workspaceId: at.id })
        const resolved = roleFor(snap, {
          terminalId: row.terminalId,
          sessionId: row.sessionId ?? null,
          workspaceId: at.id,
          title: row.title
        })
        agents.push({ key, title: row.title ?? key, ...resolved })
      }
    }
    const org = await orgChart()
    return {
      workspace: at ? { ...at, role: at.id ? (snap.roles[`workspace:${at.id}`] ?? null) : null } : null,
      agents,
      org: org.rows,
      warnings: [...policyWarnings, ...org.warnings]
    }
  }

  async function saveRole(target: 'agent' | 'workspace', key: string, role: Role | null): Promise<void> {
    if (role) snap.roles[`${target}:${key}`] = role
    else delete snap.roles[`${target}:${key}`]
    await orca.storage.set(ROLES_KEY, { ...snap.roles })
    orca.panels.post('conductor.changed', {})
  }

  async function step(args: string[], stdin = ''): Promise<StepReport> {
    const result = await runCoordinator(setup(), args, stdin)
    orca.panels.post('conductor.changed', {})
    return { ok: result.ok, lines: result.output.split('\n').filter((line) => line !== '') }
  }

  async function setFocusedRole(role: Role | null): Promise<string> {
    const at = focused
    if (!at?.id) return 'Focus a workspace first.'
    await saveRole('workspace', at.id, role)
    return role ? `${at.name} is now a ${role} workspace.` : `${at.name} has no workspace role now.`
  }

  await loadSettings()
  await loadRoles()

  // Panel requests ---------------------------------------------------------------------------
  orca.panels.handle('conductor.state', () => panelState())
  orca.panels.handle('conductor.setRole', async ({ target, key, role }) => {
    await saveRole(target, key, role)
    return panelState()
  })
  orca.panels.handle('conductor.sleep', async ({ session, ...parts }) => {
    const made = sleepNote(parts)
    if ('error' in made) return { ok: false, lines: [made.error] }
    return step(['sleep', session, `--note=${made.note}`])
  })
  orca.panels.handle('conductor.wake', async ({ session, handover }) => {
    const text = (handover ?? '').trim()
    return step(text === '' ? ['wake', session] : ['wake', session, '--handover', '-'], text)
  })

  // Palette commands -------------------------------------------------------------------------
  orca.commands.register('role.coordinator', () => setFocusedRole('coordinator'))
  orca.commands.register('role.worker', () => setFocusedRole('worker'))
  orca.commands.register('role.conductor', () => setFocusedRole('conductor'))
  orca.commands.register('role.clear', () => setFocusedRole(null))

  // Events -----------------------------------------------------------------------------------
  orca.settings.onDidChange(() => {
    void loadSettings().then(() => orca.panels.post('conductor.changed', {}))
  })
  orca.events.on('agent.status.changed', (event) => {
    if (event.workspaceId && event.workspaceListId) snap.workspaceIds.set(event.workspaceId, event.workspaceListId)
    remember(event.terminalId, {
      title: event.title,
      sessionId: event.sessionId,
      workspaceId: event.workspaceId ? listedWorkspace(snap, event.workspaceId) : null
    })
  })
  orca.events.on('workspace.created', (event) => {
    if (event.workspaceListId) snap.workspaceIds.set(event.workspaceId, event.workspaceListId)
  })
  orca.events.on('workspace.changed', ({ context }) => {
    focused = context ? { id: context.workspaceId ?? null, name: context.displayName || context.branch } : null
    for (const terminal of context?.terminals ?? []) {
      remember(terminal.id, { title: terminal.title, workspaceId: context?.workspaceId })
    }
    orca.panels.post('conductor.changed', {})
  })

  void scanAll()
}
