import { expect, test } from 'claude-code/testing'

const PUBLIC = '/Users/x/Desktop/Obsidian/99_public/content/about.md'
const CREATE = 'mcp__claude_ai_Google_Calendar__create_event'

test('公開領域に非公開ノートへのリンクを書くと止める', async ($, on) => {
  on('tool.call', () => ({ result: 'written' }) as never)
  const r = await $.tool.call({ tool: 'Write', file_path: PUBLIC, content: '[x](../08_people/a.md)' })
  expect(r.deny).toContain('08_people/')
})

test('公開領域でも問題ないリンクは通す', async ($, on) => {
  on('tool.call', () => ({ result: 'written' }) as never)
  const r = await $.tool.call({ tool: 'Write', file_path: PUBLIC, content: '[x](../00_self/README.md)' })
  expect(r.deny).toBeUndefined()
})

test('非公開領域では止めない', async ($, on) => {
  on('tool.call', () => ({ result: 'written' }) as never)
  const r = await $.tool.call({
    tool: 'Write',
    file_path: '/Users/x/Desktop/Obsidian/02_note/a.md',
    content: '[x](../08_people/a.md)',
  })
  expect(r.deny).toBeUndefined()
})

test('色なしの予定は1回止め、同じ引数の再実行は通す', async ($, on) => {
  on('tool.call', () => ({ result: 'created' }) as never)
  const args = { tool: CREATE, summary: '机運び', startTime: '2026-10-10T10:00:00+09:00', endTime: '2026-10-10T11:00:00+09:00' }
  const first = await $.tool.call(args as never)
  expect(first.deny).toContain('colorId')
  const second = await $.tool.call(args as never)
  expect(second.deny).toBeUndefined()
})

test('ピーコックと、+09:00の終日予定は止める', async ($, on) => {
  on('tool.call', () => ({ result: 'created' }) as never)
  const peacock = await $.tool.call({ tool: CREATE, summary: 'a', startTime: '2026-10-10T10:00:00+09:00', endTime: '2026-10-10T11:00:00+09:00', colorId: '7' } as never)
  expect(peacock.deny).toContain('ピーコック')
  const allDay = await $.tool.call({ tool: CREATE, summary: 'b', allDay: true, startTime: '2026-12-23T00:00:00+09:00', endTime: '2026-12-24T00:00:00+09:00', colorId: '5' } as never)
  expect(allDay.deny).toContain('Z')
})
