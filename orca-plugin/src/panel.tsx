// The Conductor sidebar panel: the org chart (awake and asleep coordinators with their notes),
// sleep and wake, and the roles of the agents in the focused workspace.
// Everything is Orca's own components, so it follows the person's theme.
import {
  atom,
  Badge,
  Box,
  Button,
  Callout,
  EmptyState,
  Heading,
  Input,
  plugin,
  read,
  RelativeTime,
  Row,
  Select,
  set,
  Stack,
  Text,
  type PanelContext
} from 'orca'
import type { OrgEntry, PanelState, StepReport } from './protocol.ts'

// Sleep and wake wait on python3 and several orca CLI calls.
const STEP_TIMEOUT_MS = 90_000

const state = atom<PanelState | null>(null)
const error = atom<string | null>(null)
const report = atom<StepReport | null>(null)
/** The coordinator whose sleep form is open, and its three parts. */
const sleeping = atom<string | null>('sleeping', null)
const owns = atom('sleep.owns', '')
const why = atom('sleep.why', '')
const notes = atom('sleep.notes', '')
const waking = atom<string | null>('waking', null)
const handover = atom('wake.handover', '')

const ROLE_OPTIONS = [
  { value: 'none', label: 'No role' },
  { value: 'conductor', label: 'Conductor' },
  { value: 'coordinator', label: 'Coordinator' },
  { value: 'worker', label: 'Worker' }
]

async function refresh(): Promise<void> {
  try {
    set(state, await plugin.request('conductor.state'))
    set(error, null)
  } catch (err) {
    set(error, (err as Error).message)
  }
}

async function setRole(target: 'agent' | 'workspace', key: string, value: string): Promise<void> {
  try {
    const role = value === 'none' ? null : (value as 'conductor' | 'coordinator' | 'worker')
    set(state, await plugin.request('conductor.setRole', { target, key, role }))
  } catch (err) {
    set(error, (err as Error).message)
  }
}

function clearForms(): void {
  set(owns, '')
  set(why, '')
  set(notes, '')
  set(handover, '')
}

function toggleSleep(session: string): void {
  clearForms()
  set(waking, null)
  set(sleeping, read(sleeping) === session ? null : session)
}

function toggleWake(session: string): void {
  clearForms()
  set(sleeping, null)
  set(waking, read(waking) === session ? null : session)
}

async function step(task: () => Promise<StepReport>): Promise<void> {
  set(error, null)
  try {
    const result = await task()
    set(report, result)
    if (result.ok) {
      set(sleeping, null)
      set(waking, null)
      clearForms()
    }
  } catch (err) {
    set(error, (err as Error).message)
  }
}

export function setup(ctx: PanelContext): void {
  ctx.subscriptions.push(plugin.on('conductor.changed', () => void refresh()))
  void refresh()
}

function SleepForm({ row }: { row: OrgEntry }) {
  const ready = read(owns).trim() !== '' && read(why).trim() !== '' && read(notes).trim() !== ''
  return (
    <Stack gap="xs">
      <Input label="What it owns" placeholder="The initiative, its repos and open items" value={read(owns)} onChange={(v) => set(owns, v)} />
      <Input label="Why it sleeps" placeholder="Shipped, waiting on the next phase" value={read(why)} onChange={(v) => set(why, v)} />
      <Input label="Where its notes live" placeholder="conductor/wiki/<topic>/" value={read(notes)} onChange={(v) => set(notes, v)} />
      <Button
        size="sm"
        icon="pause"
        disabled={!ready}
        onPress={() =>
          step(() =>
            plugin.request(
              'conductor.sleep',
              { session: row.session, owns: read(owns), why: read(why), notes: read(notes) },
              { timeoutMs: STEP_TIMEOUT_MS }
            )
          )
        }
      >
        Mark asleep
      </Button>
    </Stack>
  )
}

function WakeForm({ row }: { row: OrgEntry }) {
  return (
    <Stack gap="xs">
      <Input
        label="Handover (optional)"
        placeholder="What came back, with links"
        value={read(handover)}
        onChange={(v) => set(handover, v)}
      />
      <Button
        size="sm"
        icon="play"
        onPress={() =>
          step(() =>
            plugin.request('conductor.wake', { session: row.session, handover: read(handover) }, { timeoutMs: STEP_TIMEOUT_MS })
          )
        }
      >
        Wake and hand over
      </Button>
    </Stack>
  )
}

function OrgRow({ row }: { row: OrgEntry }) {
  return (
    <Box border radius="md" padding="sm" gap="xs">
      <Row justify="between" align="start" gap="xs">
        <Stack gap="none">
          <Text weight="medium" truncate>
            {row.name}
          </Text>
          <Text size="xs" muted>
            {row.role}
            {row.state ? ` • ${row.state}` : ''}
            {row.lastActivityAt ? ' • ' : ''}
            {row.lastActivityAt ? <RelativeTime at={row.lastActivityAt} /> : null}
          </Text>
        </Stack>
        <Badge tone={row.asleep ? 'neutral' : 'success'}>{row.asleep ? 'asleep' : 'awake'}</Badge>
      </Row>
      <Text size="xs" muted>
        {row.note || row.owns}
      </Text>
      {row.role === 'coordinator' ? (
        <Row gap="xs">
          {row.asleep ? (
            <Button size="xs" variant="ghost" icon="play" onPress={() => toggleWake(row.session)}>
              Wake
            </Button>
          ) : (
            <Button size="xs" variant="ghost" icon="pause" onPress={() => toggleSleep(row.session)}>
              Sleep
            </Button>
          )}
        </Row>
      ) : null}
      {read(sleeping) === row.session ? <SleepForm row={row} /> : null}
      {read(waking) === row.session ? <WakeForm row={row} /> : null}
    </Box>
  )
}

export default function Panel() {
  const current = read(state)
  const message = read(error)
  const last = read(report)
  return (
    <Stack gap="md">
      {message ? (
        <Callout tone="danger" icon="error" title="That did not work">
          <Text size="xs">{message}</Text>
        </Callout>
      ) : null}
      {last ? (
        <Callout tone={last.ok ? 'success' : 'warning'} icon={last.ok ? 'check' : 'warning'} title={last.ok ? 'Done' : 'Not finished'}>
          <Stack gap="none">
            {last.lines.map((line, index) => (
              <Text key={index} size="xs">
                {line}
              </Text>
            ))}
            <Button size="xs" variant="ghost" onPress={() => set(report, null)}>
              Dismiss
            </Button>
          </Stack>
        </Callout>
      ) : null}
      {(current?.warnings ?? []).map((warning, index) => (
        <Callout key={index} tone="warning" icon="warning" title="Needs attention">
          <Text size="xs">{warning}</Text>
        </Callout>
      ))}

      <Row justify="between" align="start" gap="xs">
        <Heading level={3}>Org chart</Heading>
        <Button size="xs" variant="ghost" icon="refresh" onPress={() => refresh()}>
          Refresh
        </Button>
      </Row>
      {current === null ? (
        <Text size="xs" muted>
          Loading...
        </Text>
      ) : current.org.length === 0 ? (
        <EmptyState icon="agent" title="No coordinators yet" description="Register one in the home repo with: coordinator new" />
      ) : (
        <Stack gap="sm">
          {current.org.map((row) => (
            <OrgRow key={row.session} row={row} />
          ))}
        </Stack>
      )}

      {current?.workspace ? (
        <Stack gap="sm">
          <Heading level={3}>{`Roles in ${current.workspace.name}`}</Heading>
          {current.workspace.id ? (
            <Select
              label="Workspace role (the fallback)"
              value={current.workspace.role ?? 'none'}
              options={ROLE_OPTIONS}
              onChange={(value) => setRole('workspace', current.workspace?.id ?? '', value)}
            />
          ) : null}
          {current.agents.map((agent) => (
            <Select
              key={agent.key}
              label={`${agent.title}${agent.source && agent.source !== 'agent' ? ` (${agent.role} from ${agent.source})` : ''}`}
              value={agent.source === 'agent' && agent.role ? agent.role : 'none'}
              options={ROLE_OPTIONS}
              onChange={(value) => setRole('agent', agent.key, value)}
            />
          ))}
        </Stack>
      ) : null}
    </Stack>
  )
}
