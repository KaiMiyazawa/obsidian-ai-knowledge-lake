import { expect, test } from 'claude-code/testing'

const PROPS = { hasSurvey: false, isWorking: false, maxRows: 5, bodyColumns: 100, scroll: { bodyRows: 5, top: 0, of: 5 }, view: {} }

test('計測値を受けて文脈と利用枠を1行で出す', async ($, on) => {
  on('session.model', () => ({ value: 'Opus 5.5' }) as never)
  on('session.measure', ($, e) => ({ changed: e.changed }) as never)
  await $.session.measure({
    context: { window: 200000, tokens: 182000, percent: 91 },
    rateLimits: [{ kind: 'five_hour', percentUsed: 42, resetsAt: '2026-10-05T10:00:00Z' }],
    changed: ['context', 'rateLimits'],
  } as never)
  const ui = await $.ui.mount({ plugin: 'status-band', surface: 'terminal', component: 'AbovePrompt', props: PROPS as never })
  expect(await ui.find({ type: 'Text', text: /91%/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /5時間/ })).toBeDefined()
})
