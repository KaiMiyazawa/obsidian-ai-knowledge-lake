import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { BoardMessage, BoardProps, Task, TaskLists } from '../types'

const PANE = 'tasks'
const SERVER = 'gtasks'
const REFRESH_MS = 10 * 60 * 1000

// AGENTS.md「タスクリストの使い分け」。agentsはAIに投げればよいもの、ほかは本人が動くもの。
const LISTS = [
  { key: 'agents', hotkey: 'a', id: '<AGENTS_LIST_ID>' },
  { key: 'main', hotkey: 'm', id: '<MAIN_LIST_ID>' },
  { key: 'big', hotkey: 'b', id: '<BIG_LIST_ID>' },
  { key: 'repeat', hotkey: 'r', id: '<REPEAT_LIST_ID>' },
  // 一時的な用件専用のリスト。用件が片付いたらリストごと削除し、この行も消す。
  { key: 'project', hotkey: 'i', id: '<PROJECT_LIST_ID>' },
] as const

const lists = atom({ plugin: 'tasks-pane', key: 'lists' } as const, {})
const selected = atom({ plugin: 'tasks-pane', key: 'selected' } as const, 'agents')
const fetchedAt = atom({ plugin: 'tasks-pane', key: 'fetchedAt' } as const, null)
const failure = atom({ plugin: 'tasks-pane', key: 'error' } as const, null)

// gtasks の list_with_tree の1行。子タスクは字下げされ、末尾に " parent:<id>" が付く。
// "  [ ] タイトル (due: 2026-10-19T00:00:00.000Z) | id:xxx parent:yyy"
const LINE = /^(\s*)\[( |x)\] (.*?)(?: \(due: (\d{4}-\d{2}-\d{2})[^)]*\))? \| id:(\S+)(?: parent:\S+)?\s*$/

const parse = (text: string): Task[] =>
  text.split('\n').flatMap(line => {
    const m = line.match(LINE)
    if (!m || m[2] === 'x') return []
    const [, indent = '', , title = '', due, id = ''] = m
    return [{ depth: Math.floor(indent.length / 2), title, due: due ?? null, id }]
  })

// $.mcp.call は gtasks を「未接続」と判定することがある（2026-10-05）。そのときはモデルと同じツール呼び出しで取る。
const fetchTree = async ($: EngineInterface, taskListId: string, key: string) => {
  const direct = await $.mcp.call(SERVER, 'list_with_tree', { taskListId }).catch(() => undefined)
  if (direct !== undefined && !direct.isError) {
    return direct.content.map(b => (b.type === 'text' ? b.text : '')).join('\n')
  }
  const viaTool = await $.tool.call({ tool: `mcp__${SERVER}__list_with_tree`, taskListId } as never)
  if (viaTool.deny !== undefined || viaTool.isError === true || viaTool.text === undefined) {
    throw new Error(`${key}の取得に失敗（${viaTool.deny ?? viaTool.text ?? '応答なし'}）`)
  }
  return viaTool.text
}

// 一度でも取れたか。起動直後の取り直しと、最初のプロンプトでの取り直しを止めるのに使う。
let hasFetched = false

// quiet のときは失敗をパネルに出さない（起動直後の再試行中は「読み込み中…」のままにする）。
const refresh = async ($: EngineInterface, { quiet = false } = {}) => {
  try {
    const next: TaskLists = {}
    for (const list of LISTS) {
      next[list.key] = parse(await fetchTree($, list.id, list.key))
    }
    await update($, lists, () => next)
    await update($, failure, () => null)
    await update($, fetchedAt, () => Date.now())
    hasFetched = true
    return true
  } catch (err) {
    if (!quiet) await update($, failure, () => String(err instanceof Error ? err.message : err))
    return false
  }
}

// 起動直後は gtasks の MCP がまだ繋がっておらず、ツールも未登録で失敗する（2026-10-13 確認）。
// 接続完了を知らせるイベントは無いので、間隔を倍にしながら約2分取り直す。最後の1回だけ失敗を表示する。
const RETRY_MS = [2000, 4000, 8000, 16000, 32000, 60000]

const fetchOnStart = async ($: EngineInterface, attempt = 0): Promise<void> => {
  if (hasFetched) return
  const isLast = attempt >= RETRY_MS.length
  if ((await refresh($, { quiet: !isLast })) || isLast) return
  $.clock.after(RETRY_MS[attempt] ?? 60000, () => void fetchOnStart($, attempt + 1))
}

// 入力欄に入れるだけで送信はしない。本人が「補足:」の後に文脈を足してから送れる。
// 送られた側には、前提が足りなければ着手前に質問するよう頼んでおく。
const startPrompt = ($: EngineInterface, list: string, task: Task) => {
  const ref = `Google Tasks「${list}」の「${task.title}」（id:${task.id}）`
  const ask =
    list === 'agents'
      ? `${ref}に着手して。notes と関係ノートを読み、`
      : `${ref}を進めたい。これは私が動くタスクなので、notes を読んで、AIが先に下調べ・準備できることを提案して。`
  return $.prompt.fill({
    text: `${ask}前提が足りない点や判断が要る点があれば、作業に入る前に質問して。\n\n補足: `,
    mode: 'replace',
  })
}

// 本人の操作なしに開くパネルは、ターミナルが144桁（一度開いたものは110桁）以上ないと置かれない（エンジンの仕様、2026-10-05 確認）。
// 開き直しても幅が足りなければ同じなので、置かれなかったら最初のプロンプト送信時に開く。本人の Enter が契機なら幅を問わず置かれる。
let isWaiting = false

const openUnasked = async ($: EngineInterface) => {
  const opened = await $.ui.open({ id: PANE, title: 'Tasks' })
  if (opened.isPlaced) return
  isWaiting = true
  $.ui.log(`tasks-pane: 起動時は置かれなかった（${opened.reason}）。次のプロンプトで開く`, { to: 'debug' })
}

const todayJst = () => new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10)

// 期限切れは赤、3日以内は黄、それ以外はうっすら（dim）。
const dueStyle = (due: string, today: string) => {
  if (due < today) return { color: 'red' }
  const days = (Date.parse(due) - Date.parse(today)) / 86400000
  return days <= 3 ? { color: 'yellow' } : { dimColor: true }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // /tasks は組み込みコマンドなので使えない（2026-10-05 に登録を拒否された）。AGENTS.md の「TODO＝Google Tasks」に合わせる。
    await $.command
      .register({ name: 'todo', description: 'Google Tasks（agents / main / big / repeat / project）のパネルを開いて更新する' })
      .catch((err: unknown) => $.ui.log(`tasks-pane: /todo を登録できなかった（${String(err)}）`, { to: 'debug' }))
    void fetchOnStart($)
    $.clock.every(REFRESH_MS, () => void refresh($))
    void openUnasked($)

    return next(e)
  })

  on('prompt.submit', async ($, e, next) => {
    // 再試行がまだ実っていなくても、本人がプロンプトを送る頃には MCP は繋がっている。
    if (!hasFetched && e.origin.kind === 'composer') void refresh($)
    if (isWaiting && e.origin.kind === 'composer') {
      isWaiting = false
      const isPlaced = (await $.ui.panes()).some(pane => pane.id === PANE && pane.isPlaced)
      if (!isPlaced) await $.ui.open({ id: PANE, title: 'Tasks' })
    }

    return next(e)
  })

  on('command.run', { command: 'todo' }, async $ => {
    await $.ui.open({ id: PANE, title: 'Tasks' })
    await refresh($)

    return { text: 'Tasksパネルを更新した。' }
  })

  // モデルがタスクを書き換えたら、パネルも追従させる。
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    const tool = String(e.tool)
    if (tool.startsWith(`mcp__${SERVER}__`) && !/__(list|search)/.test(tool)) void refresh($)

    return ran
  })

  on('ui.message', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const message = e.data as BoardMessage
    if (message.type === 'select') await update($, selected, () => message.list)
    else if (message.type === 'start') await startPrompt($, message.list, message.task)
    else if (message.type === 'refresh') await refresh($)

    return {}
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const all = await read($, lists)
    const current = await read($, selected)
    const error = await read($, failure)
    const isLoading = (await read($, fetchedAt)) === null && error === null
    const today = todayJst()

    // ターミナルは Client で矢印キーを受ける。
    if (e.surface === 'terminal') {
      const { Client } = $.ui.resolve(e)
      const props: BoardProps = {
        lists: LISTS.map(l => ({ key: l.key, tasks: all[l.key] ?? [] })),
        current,
        today,
        error,
        isLoading,
      }
      // 大きさを渡さないと、描くたびに測り直して落ち着かない。
      return (
        <Client
          key="board"
          module="./board.tsx"
          props={props}
          width={e.props.bodyColumns}
          height={Math.max(5, e.props.scroll.bodyRows)}
        />
      )
    }

    // ほかの画面はボタンで操作する。
    const { Box, Button, Text } = $.ui.resolve(e)
    const tasks = all[current] ?? []

    return (
      <Box flexDirection="column">
        <Box flexWrap="wrap" columnGap={1}>
          {LISTS.map(list => (
            <Button
              key={list.key}
              label={`${list.key} ${all[list.key]?.length ?? '-'}`}
              hotkey={list.hotkey}
              variant={list.key === current ? 'primary' : undefined}
              onPress={() => update($, selected, () => list.key)}
            />
          ))}
          <Button key="refresh" label="更新" hotkey="u" onPress={() => refresh($)} />
        </Box>
        {error !== null && <Text color="red">{error}</Text>}
        {isLoading && <Text dimColor>読み込み中…</Text>}
        {!isLoading && tasks.length === 0 && <Text dimColor>タスクなし</Text>}
        {tasks.map(task => (
          <Box key={task.id} columnGap={1}>
            <Button key={`go-${task.id}`} label="着手" plain onPress={() => startPrompt($, current, task)} />
            {task.due !== null && <Text {...dueStyle(task.due, today)}>{task.due.slice(5).replace('-', '/')}</Text>}
            <Text wrap="truncate-end">
              {'  '.repeat(task.depth)}
              {task.title}
            </Text>
          </Box>
        ))}
      </Box>
    )
  })
}
