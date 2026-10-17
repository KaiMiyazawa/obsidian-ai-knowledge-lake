import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

// 子タスクの行には " parent:<id>" が付く（実際の gtasks の出力どおり）。
const TREE = [
  'Task tree (2 tasks):',
  '[ ] 期限切れのタスク (due: 2020-01-01T00:00:00.000Z) | id:old1',
  '  [ ] 期限つきの子タスク (due: 2099-01-01T00:00:00.000Z) | id:child1 parent:old1',
].join('\n')

const PROPS = { title: 'Tasks', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { bodyRows: 20, top: 0, of: 20 } }

const setup = (on: On) => {
  const asked: string[] = []
  const filled: string[] = []
  on('mcp.call', ($, e) => {
    asked.push(String((e as { args?: { taskListId?: string } }).args?.taskListId))
    return { value: { content: [{ type: 'text', text: TREE }], isError: false } } as never
  })
  on('prompt.fill', ($, e) => {
    filled.push(e.text)
    return { isFilled: true } as never
  })
  on('ui.open', () => ({ value: { isOpen: true } }) as never)
  return { asked, filled }
}

test('5リストを取得し、子タスクの日付も読む（ボタン表示の画面）', async ($, on) => {
  const { asked, filled } = setup(on)
  await $.command.run({ command: 'todo', args: '' } as never)
  expect(asked.length).toBe(5)

  const ui = await $.ui.mount({ plugin: 'tasks-pane', surface: 'desktop', component: 'Pane', requestId: 'tasks', props: PROPS as never })
  expect(await ui.find({ type: 'Text', text: /期限つきの子タスク/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '01/01' })).toBeDefined()

  await $.ui.press({ plugin: 'tasks-pane', key: 'go-child1' })
  expect(filled[0]).toContain('id:child1')
  expect(filled[0]).toContain('質問して')
})

test('ターミナルでは ←→ でリスト、↑↓ でタスク、Enter で着手できる', async ($, on) => {
  const { filled } = setup(on)
  await $.command.run({ command: 'todo', args: '' } as never)

  const ui = await $.ui.mount({ plugin: 'tasks-pane', surface: 'terminal', component: 'Pane', requestId: 'tasks', props: PROPS as never })
  expect(await ui.drawn()).toBeDefined()

  // → で main へ、↓ で子タスクへ、Enter で着手。
  await ui.key({ key: 'right', in: 'board' })
  await ui.key({ key: 'down', in: 'board' })
  await ui.key({ key: 'return', in: 'board' })
  expect(filled[0]).toContain('「main」')
  expect(filled[0]).toContain('id:child1')
  expect(filled[0]).toContain('私が動くタスク')
  expect(filled[0]).toContain('補足: ')
})

test('$.mcp.call が gtasks を未接続と言っても、ツール呼び出しで取り直す', async ($, on) => {
  const viaTool: string[] = []
  on('mcp.call', () => ({ deny: 'no connected MCP tool "list_with_tree" on a server named "gtasks"' }) as never)
  on('tool.call', ($, e) => {
    viaTool.push(String(e.tool))
    return { result: TREE, text: TREE } as never
  })
  on('ui.open', () => ({ value: { isOpen: true } }) as never)
  await $.command.run({ command: 'todo', args: '' } as never)
  expect(viaTool.length).toBe(5)

  const ui = await $.ui.mount({ plugin: 'tasks-pane', surface: 'desktop', component: 'Pane', requestId: 'tasks', props: PROPS as never })
  expect(await ui.find({ type: 'Text', text: /期限切れのタスク/ })).toBeDefined()
})

test('起動時に置かれなかったら、本人の最初のプロンプトで開き直す', async ($, on) => {
  on('mcp.call', () => ({ value: { content: [{ type: 'text', text: TREE }], isError: false } }) as never)
  const opens: number[] = []
  on('ui.open', () => {
    opens.push(opens.length)
    return { value: opens.length === 1 ? { isPlaced: false, reason: 'narrow' } : { isPlaced: true } } as never
  })
  on('ui.panes', () => ({ value: [] }) as never)
  on('ui.log', () => ({ value: undefined }) as never)
  on('clock.every', () => ({ value: undefined }) as never)
  on('command.register', () => ({ value: undefined }) as never)
  on('session.start', ($, e) => e as never)
  on('prompt.submit', ($, e) => e as never)
  await $.session.start({ cwd: '/tmp' } as never)
  expect(opens.length).toBe(1)

  await $.prompt.submit({ text: 'hi', origin: { kind: 'composer' } } as never)
  expect(opens.length).toBe(2)
  await $.prompt.submit({ text: 'again', origin: { kind: 'composer' } } as never)
  expect(opens.length).toBe(2)
  // 起動時に裏で走らせた取得が終わるのを待つ。
  await $.command.run({ command: 'todo', args: '' } as never)
})

// 起動直後は gtasks が未接続で、$.mcp.call もツール呼び出しも失敗する。失敗した取得は最初のリストで止まるので1回だけ呼ぶ。
const startOffline = (on: On, failures: number) => {
  let calls = 0
  on('mcp.call', () => {
    calls += 1
    return (calls <= failures ? { deny: 'not connected' } : { value: { content: [{ type: 'text', text: TREE }], isError: false } }) as never
  })
  on('tool.call', () => ({ deny: 'no tool named "mcp__gtasks__list_with_tree" in this session' }) as never)
  on('ui.open', () => ({ value: { isPlaced: true } }) as never)
  on('ui.log', () => ({ value: undefined }) as never)
  on('command.register', () => ({ value: undefined }) as never)
  on('session.start', ($, e) => e as never)
  on('prompt.submit', ($, e) => e as never)
  return { clock: mock.clock(on), calls: () => calls }
}

const mountDesktop = ($: Parameters<Parameters<typeof test>[1]>[0]) =>
  $.ui.mount({ plugin: 'tasks-pane', surface: 'desktop', component: 'Pane', requestId: 'tasks', props: PROPS as never })

test('起動直後に未接続でも、間隔を空けて取り直し、途中の失敗は表示しない', async ($, on) => {
  const { clock, calls } = startOffline(on, 2)
  await $.session.start({ cwd: '/tmp' } as never)
  await clock.settle()
  expect(calls()).toBe(1)
  const ui = await mountDesktop($)
  expect(await ui.find({ type: 'Text', text: /取得に失敗/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: '読み込み中…' })).toBeDefined()

  await clock.advance(2000)
  expect(calls()).toBe(2)
  await clock.advance(4000)
  expect(await ui.find({ type: 'Text', text: /期限切れのタスク/ })).toBeDefined()
})

test('再試行を使い切ったら、最後の失敗だけを表示する', async ($, on) => {
  const { clock, calls } = startOffline(on, 99)
  await $.session.start({ cwd: '/tmp' } as never)
  await clock.advance(2000 + 4000 + 8000 + 16000 + 32000 + 60000)
  expect(calls()).toBe(7)
  expect(await (await mountDesktop($)).find({ type: 'Text', text: /agentsの取得に失敗/ })).toBeDefined()
})

test('まだ取れていなければ、本人の最初のプロンプトで取り直す', async ($, on) => {
  const { clock, calls } = startOffline(on, 1)
  await $.session.start({ cwd: '/tmp' } as never)
  await clock.settle()
  expect(calls()).toBe(1)

  await $.prompt.submit({ text: 'hi', origin: { kind: 'composer' } } as never)
  await clock.settle()
  expect(await (await mountDesktop($)).find({ type: 'Text', text: /期限切れのタスク/ })).toBeDefined()
})
