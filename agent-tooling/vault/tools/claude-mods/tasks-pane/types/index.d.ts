export type Task = {
  id: string
  title: string
  due: string | null
  depth: number
}

export type TaskLists = Record<string, Task[]>

// フック → ターミナルのパネル（board.tsx）へ渡すもの。
export type BoardProps = {
  lists: { key: string; tasks: Task[] }[]
  current: string
  today: string
  error: string | null
  isLoading: boolean
}

// パネル → フックへ送るもの。
export type BoardMessage =
  | { type: 'select'; list: string }
  | { type: 'start'; list: string; task: Task }
  | { type: 'refresh' }

declare module 'claude-code' {
  interface PluginState {
    'tasks-pane': {
      lists: TaskLists
      selected: string
      fetchedAt: number | null
      error: string | null
    }
  }
}
