import type { Register } from 'claude-code'

// 公開前提の領域（AGENTS.md「編集時の注意」）。ここへの書き込みに、名前で中身が分かる非公開ノートへの参照を入れさせない。
const PUBLIC_AREA = /\/Obsidian\/(99_public|89_profile)\//
const PRIVATE_REF = /(08_people\/|06_health\/|relationship-end)/

// 02_note/calendar-color-rules.md の要約。拒否理由としてモデルに渡すので、mdを読み直さなくて済む量に絞る。
const CALENDAR_RULES = [
  '色ルール（02_note/calendar-color-rules.md）: 赤→オレンジ→仮→時間だけ→ジャンル、の順に決める。',
  '11=重要(取り返しがつかない。月5件まで、迷ったら6) / 6=準重要 / 1=仮・未確定 / 9=大学・学び / 10=仕事・収入 /',
  '3=プライベート / 4=健康・通院 / 8=繰り返しの生活予定 / 5=目印・期間 / 指定なし=雑多な用事 / 7(ピーコック)は使わない。',
].join('\n')

const CALENDAR = 'mcp__claude_ai_Google_Calendar__'

type CalendarArgs = {
  summary?: string
  startTime?: string
  endTime?: string
  allDay?: boolean
  colorId?: string
}

// 終日予定を+09:00で渡すと1日前にずれる（2026-10-01に実際にずれた）。
const allDayOffsetProblem = (a: CalendarArgs) =>
  a.allDay === true && [a.startTime, a.endTime].some(t => t !== undefined && !t.endsWith('Z'))

export const register: Register = on => {
  on('tool.call', { tool: 'Write' }, ($, e, next) =>
    PUBLIC_AREA.test(e.file_path) && PRIVATE_REF.test(e.content)
      ? { deny: publicDeny(e.content) }
      : next(e),
  )

  on('tool.call', { tool: 'Edit' }, ($, e, next) =>
    PUBLIC_AREA.test(e.file_path) && PRIVATE_REF.test(e.new_string)
      ? { deny: publicDeny(e.new_string) }
      : next(e),
  )

  // 色なしの1回目は止めて確認させ、同じ引数での再実行は「雑多な用事」として通す。
  const confirmedUncolored = new Set<string>()

  on('tool.call', ($, e, next) => {
    const tool = String(e.tool)
    if (!tool.startsWith(CALENDAR)) return next(e)
    const isCreate = tool === `${CALENDAR}create_event`
    if (!isCreate && tool !== `${CALENDAR}update_event`) return next(e)

    const args = e as unknown as CalendarArgs
    if (args.colorId === '7') {
      return { deny: `vault-guard: colorId 7（ピーコック）は使わない。\n${CALENDAR_RULES}` }
    }
    if (allDayOffsetProblem(args)) {
      return {
        deny: 'vault-guard: 終日予定の日付は 2026-12-23T00:00:00Z のように Z で渡す（+09:00 だと1日ずれる）。終了日は最終日の翌日。',
      }
    }
    if (isCreate && args.colorId === undefined) {
      const key = `${args.summary}|${args.startTime}`
      if (!confirmedUncolored.has(key)) {
        confirmedUncolored.add(key)
        return {
          deny: `vault-guard: colorId が未指定。\n${CALENDAR_RULES}\n雑多な用事で本当に色なしなら、同じ引数のまま再実行すれば通る。`,
        }
      }
    }

    return next(e)
  })
}

const publicDeny = (text: string) => {
  const hit = text.match(PRIVATE_REF)?.[0]
  return `vault-guard: 公開領域（99_public / 89_profile）に非公開ノートへの参照「${hit}」が入っている。公開サイトでも GitHub 上でパスが見えるので外す（AGENTS.md「編集時の注意」）。`
}
