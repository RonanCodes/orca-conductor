// Model by role: a policy such as "coordinator=opus:high; worker=sonnet:medium", applied to an
// agent's launch command. Aliases only: a pinned model id goes stale when a newer model ships.

import { isRole, type Role } from './roles.ts'

export type Effort = 'low' | 'medium' | 'high' | 'xhigh' | 'max'
export const EFFORTS: readonly Effort[] = ['low', 'medium', 'high', 'xhigh', 'max']

export type RoleModel = { model: string; effort?: Effort }
export type Policy = Partial<Record<Role, RoleModel>>

export const DEFAULT_POLICY_TEXT = 'conductor=opus:high; coordinator=opus:high; worker=sonnet:medium'

/** A model alias: lower-case letters and dashes, no digits, so a full model id is refused. */
export function isAlias(value: string): boolean {
  return /^[a-z][a-z-]*$/.test(value) && !value.startsWith('claude-')
}

export type ParsedPolicy = { policy: Policy; errors: string[] }

/** Parses the policy text. Bad entries are skipped and named in `errors`; the rest still apply. */
export function parsePolicy(text: unknown): ParsedPolicy {
  const source = typeof text === 'string' && text.trim() !== '' ? text : DEFAULT_POLICY_TEXT
  const policy: Policy = {}
  const errors: string[] = []
  for (const raw of source.split(/[;\n]+/)) {
    const entry = raw.trim()
    if (entry === '') continue
    const match = /^([a-z]+)\s*=\s*([^:\s]+)(?:\s*:\s*([a-z]+))?$/i.exec(entry)
    if (!match) {
      errors.push(`"${entry}" is not role=model or role=model:effort`)
      continue
    }
    const role = match[1].toLowerCase()
    const model = match[2].toLowerCase()
    const effort = match[3]?.toLowerCase()
    if (!isRole(role)) {
      errors.push(`"${role}" is not a role (conductor, coordinator, worker)`)
      continue
    }
    if (!isAlias(model)) {
      errors.push(`"${model}" is not a model alias (use opus, sonnet, haiku and the like, never a full id)`)
      continue
    }
    if (effort !== undefined && !(EFFORTS as readonly string[]).includes(effort)) {
      errors.push(`"${effort}" is not an effort (${EFFORTS.join(', ')})`)
      continue
    }
    policy[role] = effort ? { model, effort: effort as Effort } : { model }
  }
  return { policy, errors }
}

type Word = { text: string; start: number; end: number; quoted: boolean; separator: boolean }

/** A POSIX command line as words and separators, or null when a quote is left open. */
function splitCommand(command: string): Word[] | null {
  const words: Word[] = []
  let i = 0
  while (i < command.length) {
    const start = i
    const char = command[i]
    if (';&|()\n'.includes(char)) {
      words.push({ text: char, start, end: start + 1, quoted: false, separator: true })
      i += 1
      continue
    }
    if (/\s/.test(char)) {
      i += 1
      continue
    }
    let text = ''
    let quoted = false
    while (i < command.length && !/[\s;&|()]/.test(command[i])) {
      const part = command[i]
      if (part === "'" || part === '"') {
        quoted = true
        i += 1
        while (i < command.length && command[i] !== part) {
          if (part === '"' && command[i] === '\\') i += 1
          text += command[i] ?? ''
          i += 1
        }
        if (i >= command.length) return null
        i += 1
      } else {
        if (part === '\\') i += 1
        text += command[i] ?? ''
        i += 1
      }
    }
    words.push({ text, start, end: i, quoted, separator: false })
  }
  return words
}

/**
 * The command with the role's model and effort added after the `claude` executable. Unchanged when
 * the role has no entry, when that claude call already names both flags, or when `claude` is not
 * run as a command. The word claude in a prompt or a folder name is never touched.
 */
export function applyPolicy(command: string, role: Role | null, policy: Policy): string {
  if (role === null) return command
  const entry = policy[role]
  if (!entry) return command
  const words = splitCommand(command)
  if (!words) return command
  let commandStart = true
  for (let i = 0; i < words.length; i += 1) {
    const word = words[i]
    if (word.separator) {
      commandStart = true
      continue
    }
    if (!commandStart) continue
    if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(word.text)) continue
    commandStart = false
    if (word.text.split('/').pop() !== 'claude') continue
    const given = new Set<string>()
    for (const arg of words.slice(i + 1)) {
      if (arg.separator || arg.text === '--') break
      // A quoted word with a space is a prompt, whatever it starts with.
      if (arg.quoted && /\s/.test(arg.text)) continue
      given.add(arg.text.split('=')[0])
    }
    const flags: string[] = []
    if (!given.has('--model')) flags.push('--model', entry.model)
    if (entry.effort && !given.has('--effort')) flags.push('--effort', entry.effort)
    if (flags.length === 0) return command
    return `${command.slice(0, word.end)} ${flags.join(' ')}${command.slice(word.end)}`
  }
  return command
}
