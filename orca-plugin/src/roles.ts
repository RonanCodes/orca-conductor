// Roles: conductor, coordinator or worker, per agent or per workspace.
// Pure functions only, so they run under `node --test` and inside the Orca worker alike.

export type Role = 'conductor' | 'coordinator' | 'worker'

export const ROLES: readonly Role[] = ['conductor', 'coordinator', 'worker']

export type Markers = Record<Role, string>

export const DEFAULT_MARKERS: Markers = {
  conductor: '🎩',
  coordinator: '🎖️',
  worker: '🤖'
}

/** Roles that may ask the person a question, by default. */
export const DEFAULT_ASK_ROLES: readonly Role[] = ['conductor', 'coordinator']

/** Emoji variation selectors (U+FE0E, U+FE0F) make one emoji compare unequal to itself. */
function bare(text: string): string {
  return text.replace(/[︎️]/g, '')
}

export function isRole(value: unknown): value is Role {
  return typeof value === 'string' && (ROLES as readonly string[]).includes(value)
}

/** Reads one marker setting; an empty or missing value keeps the default. */
export function readMarkers(settings: Record<string, unknown>): Markers {
  const pick = (key: string, fallback: string): string => {
    const value = settings[key]
    return typeof value === 'string' && value.trim() !== '' ? value.trim() : fallback
  }
  return {
    conductor: pick('markerConductor', DEFAULT_MARKERS.conductor),
    coordinator: pick('markerCoordinator', DEFAULT_MARKERS.coordinator),
    worker: pick('markerWorker', DEFAULT_MARKERS.worker)
  }
}

/**
 * The role a title's leading marker names, or null. The conductor is checked first, because its
 * title may also carry the coordinator marker (for example "🎩 🎖️🎖️ Conductor"), so a sidebar
 * filter on the coordinator marker still shows it.
 */
export function roleFromTitle(title: string | null | undefined, markers: Markers = DEFAULT_MARKERS): Role | null {
  if (!title) return null
  const text = bare(title).trimStart()
  for (const role of ['conductor', 'coordinator', 'worker'] as const) {
    const marker = bare(markers[role])
    if (marker !== '' && text.startsWith(marker)) return role
  }
  return null
}

export type RoleSources = {
  /** Set by hand for this agent (keyed by session id or terminal id). */
  agent?: Role | null
  /** Derived from the agent's title. */
  title?: Role | null
  /** Set by hand for the whole workspace. */
  workspace?: Role | null
}

/** Most specific first: the agent's own role, then its title, then its workspace. */
export function resolveRole(sources: RoleSources): Role | null {
  return sources.agent ?? sources.title ?? sources.workspace ?? null
}

/** Parses "conductor, coordinator" into roles, ignoring unknown words; empty keeps the default. */
export function parseAskRoles(value: unknown): Role[] {
  if (typeof value !== 'string' || value.trim() === '') return [...DEFAULT_ASK_ROLES]
  return value
    .split(/[\s,]+/)
    .map((word) => word.trim().toLowerCase())
    .filter(isRole)
}

/**
 * The deny reason for an AskUserQuestion call, or null to let it through. An agent with no known
 * role passes: the gate only stops roles it knows may not ask.
 */
export function askDecision(role: Role | null, askRoles: readonly Role[]): string | null {
  if (role === null || askRoles.includes(role)) return null
  const allowed = askRoles.length > 0 ? askRoles.join(' or ') : 'no role'
  return (
    `This agent's role is ${role}, and only the ${allowed} may ask the person. ` +
    'Send the question to your coordinator instead: ' +
    'orca orchestration ask --question "<your question>" ' +
    '(then end your turn; Orca wakes you with the answer). Outside a Run, use orca orchestration send to it.'
  )
}
