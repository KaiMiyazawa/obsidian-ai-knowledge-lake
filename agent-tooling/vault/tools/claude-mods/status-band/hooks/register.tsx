import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionContextUsage, SessionRateLimit } from 'claude-code'

const usage = atom({ plugin: 'status-band', key: 'usage' } as const, null)

// AGENTS.md「Claude Code Cloud Session への委譲」。期限を過ぎたら表示しない（この定数ごと消してよい）。
const CLOUD_CREDIT_EXPIRES = Date.parse('2026-11-05T16:59:00+09:00')

const JST_MS = 9 * 3600 * 1000
const LABELS: Record<string, string> = { five_hour: '5時間', seven_day: '週間' }

const jst = (iso: string, withDate: boolean) => {
  const t = new Date(Date.parse(iso) + JST_MS).toISOString()
  const hm = t.slice(11, 16)
  return withDate ? `${t.slice(5, 7)}/${t.slice(8, 10)} ${hm}` : hm
}

const levelColor = (p: number) => (p >= 90 ? 'red' : p >= 70 ? 'yellow' : 'green')

const save = async ($: EngineInterface, context: SessionContextUsage, limits: readonly SessionRateLimit[]) => {
  const model = await $.session.model()
  await update($, usage, () => ({
    model,
    contextPercent: context.percent,
    limits: limits.map(l => ({ kind: l.kind, percentUsed: l.percentUsed, resetsAt: l.resetsAt })),
  }))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const ran = await next(e)
    const now = await $.session.usage()
    await save($, now.context, now.rateLimits)

    return ran
  })

  on('session.measure', async ($, e, next) => {
    await save($, e.context, e.rateLimits)

    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const u = await read($, usage)
    if (e.props.hasSurvey || u === null) return next(e)

    const { Box, Text } = $.ui.resolve(e)
    const now = Date.now()
    const ctx = u.contextPercent
    const filled = ctx === undefined ? 0 : Math.round(ctx / 10)
    const creditDays = Math.ceil((CLOUD_CREDIT_EXPIRES - now) / 86400000)

    return (
      <Box columnGap={1} flexWrap="wrap">
        <Text dimColor>[{u.model}]</Text>
        <Text>
          文脈 {e.props.bodyColumns >= 65 && `[${'#'.repeat(filled)}${'-'.repeat(10 - filled)}] `}
        </Text>
        {ctx === undefined ? (
          <Text dimColor>未取得</Text>
        ) : (
          <Text color={levelColor(ctx)}>{ctx}%</Text>
        )}
        {u.limits
          .filter(l => LABELS[l.kind] !== undefined)
          .map(l => {
            const isPast = l.resetsAt !== undefined && Date.parse(l.resetsAt) <= now
            const reset =
              l.resetsAt === undefined ? '' : isPast ? '（更新待ち）' : `→${jst(l.resetsAt, l.kind === 'seven_day')}`
            return (
              <Text key={l.kind}>
                | {LABELS[l.kind]} <Text color={levelColor(l.percentUsed)}>{Math.round(l.percentUsed)}%</Text>
                {reset}
              </Text>
            )
          })}
        {creditDays > 0 && (
          <Text color={creditDays <= 7 ? 'yellow' : undefined} dimColor={creditDays > 7}>
            | Cloudクレジット失効まで{creditDays}日
          </Text>
        )}
      </Box>
    )
  })
}
