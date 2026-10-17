import { expect, test } from 'claude-code/testing'

test('見つからない添付があれば、確認を出す前に止める', async ($, on) => {
  on('tool.call', () => ({ result: 'sent' }) as never)
  const r = await $.tool.call({
    tool: 'mcp__gmail-unifier__send_message',
    to: ['a@example.com'],
    subject: 'テスト',
    body: '本文',
    attachment_paths: ['/no/such/file.pdf'],
  } as never)
  expect(r.deny).toContain('添付が見つからない')
})

test('送信系以外の gmail-unifier ツールには触らない', async ($, on) => {
  on('tool.call', () => ({ result: 'drafted' }) as never)
  const r = await $.tool.call({ tool: 'mcp__gmail-unifier__create_draft', to: ['a@example.com'] } as never)
  expect(r.deny).toBeUndefined()
})
