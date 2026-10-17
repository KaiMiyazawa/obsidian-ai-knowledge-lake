import type { ClientModule } from 'claude-code'

import type { BoardMessage, BoardProps } from '../types'

type State = { list: number; row: number }

// 期限切れは赤、3日以内は黄、それ以外はうっすら（dim）。
const dueStyle = (due: string, today: string) => {
  if (due < today) return { color: 'red' }
  const days = (Date.parse(due) - Date.parse(today)) / 86400000
  return days <= 3 ? { color: 'yellow' } : { dimColor: true }
}

// ターミナルのパネル本体。クリックでフォーカスを渡すと ←→ でリスト、↑↓ でタスク、Enter で着手、u で更新。
const Board: ClientModule<BoardProps, State> = (props, surface) => {
  const { Box, Text } = surface.elements
  const keys = props.lists.map(l => l.key)
  const initial = Math.max(0, keys.indexOf(props.current))
  const state = surface.state ?? { list: initial, row: 0 }
  const list = props.lists[state.list] ?? props.lists[0]
  const tasks = list?.tasks ?? []
  const row = Math.min(state.row, Math.max(0, tasks.length - 1))

  surface.onKey(event => {
    const n = props.lists.length
    if (event.key === 'left' || event.key === 'right') {
      const next = (state.list + (event.key === 'left' ? n - 1 : 1)) % n
      surface.setState({ list: next, row: 0 })
      surface.post({ type: 'select', list: keys[next] ?? '' } satisfies BoardMessage)
    } else if (event.key === 'up' || event.key === 'down') {
      const next = Math.max(0, Math.min(tasks.length - 1, row + (event.key === 'up' ? -1 : 1)))
      surface.setState({ list: state.list, row: next })
    } else if (event.key === 'return') {
      const task = tasks[row]
      if (list && task) surface.post({ type: 'start', list: list.key, task } satisfies BoardMessage)
    } else if (event.key === 'u') {
      surface.post({ type: 'refresh' } satisfies BoardMessage)
    }
  })

  // カーソル行が見える範囲だけ描く（ヘッダ2行・フッタ1行を除く）。
  const room = Math.max(3, (surface.rows || 24) - 3)
  const start = Math.max(0, Math.min(row - Math.floor(room / 2), tasks.length - room))
  const visible = tasks.slice(start, start + room)

  return (
    <Box flexDirection="column" flexGrow={1}>
      <Box columnGap={1}>
        {props.lists.map((l, i) => (
          <Text key={l.key} inverse={i === state.list} bold={i === state.list} dimColor={i !== state.list}>
            {` ${l.key} ${l.tasks.length} `}
          </Text>
        ))}
      </Box>
      {props.error !== null && <Text color="red">{props.error}</Text>}
      {props.isLoading && <Text dimColor>読み込み中…</Text>}
      {!props.isLoading && tasks.length === 0 && <Text dimColor>タスクなし</Text>}
      {visible.map((task, i) => {
        const isCursor = start + i === row
        return (
          <Box key={task.id} columnGap={1}>
            <Text color={isCursor ? 'cyan' : undefined}>{isCursor ? '›' : ' '}</Text>
            {task.due !== null && (
              <Text {...dueStyle(task.due, props.today)}>{task.due.slice(5).replace('-', '/')}</Text>
            )}
            <Text wrap="truncate-end" bold={isCursor}>
              {'  '.repeat(task.depth)}
              {task.title}
            </Text>
          </Box>
        )
      })}
      <Text dimColor>クリックで操作 ←→リスト ↑↓移動 Enter着手 u更新</Text>
    </Box>
  )
}

export default Board
