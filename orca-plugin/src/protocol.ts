// The panel <-> worker contract, declared once: src/panel.tsx and src/worker.ts both read it.
import type { Role } from './roles.ts'

export type AgentRow = {
  /** Session id when known, else terminal id. */
  key: string
  title: string
  /** The role in effect, and where it came from. */
  role: Role | null
  source: 'agent' | 'title' | 'workspace' | null
}

/** One row of `coordinator ls --json`. */
export type OrgEntry = {
  name: string
  role: 'conductor' | 'coordinator'
  owns: string
  session: string
  asleep: boolean
  note: string
  state: string | null
  lastActivityAt: number | null
}

export type PanelState = {
  workspace: { id: string | null; name: string; role: Role | null } | null
  agents: AgentRow[]
  org: OrgEntry[]
  /** What is not set up or not working, shown in the panel. */
  warnings: string[]
}

export type StepReport = { ok: boolean; lines: string[] }

declare module 'orca' {
  interface PluginRequests {
    'conductor.state': { output: PanelState }
    'conductor.setRole': {
      input: { target: 'agent' | 'workspace'; key: string; role: Role | null }
      output: PanelState
    }
    'conductor.sleep': {
      input: { session: string; owns: string; why: string; notes: string }
      output: StepReport
    }
    'conductor.wake': { input: { session: string; handover?: string }; output: StepReport }
  }
  interface PluginPanelEvents {
    'conductor.changed': Record<string, never>
  }
}
