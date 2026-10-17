export type Usage = {
  model: string
  contextPercent?: number
  limits: { kind: string; percentUsed: number; resetsAt?: string }[]
}

declare module 'claude-code' {
  interface PluginState {
    'status-band': {
      usage: Usage | null
    }
  }
}
