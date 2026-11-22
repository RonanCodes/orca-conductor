// The few Node APIs the worker uses, typed here so the plugin needs no package.json or
// @types/node. The worker runs in Node, where these exist.

declare module 'node:child_process' {
  type Readable = {
    setEncoding(encoding: 'utf8'): void
    on(event: 'data', listener: (chunk: string) => void): void
  }
  type Writable = { on(event: 'error', listener: (error: Error) => void): void; end(text: string): void }
  export type ChildProcess = {
    stdin: Writable
    stdout: Readable
    stderr: Readable
    on(event: 'error', listener: (error: Error) => void): void
    on(event: 'close', listener: (code: number | null) => void): void
  }
  export function spawn(
    file: string,
    args: readonly string[],
    options: { stdio: ['pipe', 'pipe', 'pipe']; env: Record<string, string | undefined> }
  ): ChildProcess
}

declare const process: { env: Record<string, string | undefined> }
declare function setTimeout(callback: () => void, ms: number): unknown
declare function clearTimeout(handle: unknown): void
