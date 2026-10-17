import type { McpToolResult, Register } from 'claude-code'

const SERVER = 'gmail-unifier'
const PREFIX = `mcp__${SERVER}__`
const SEND_TOOLS = new Set(['send_message', 'send_reply', 'forward', 'send_draft'])

const SEND = '送信する'
const CANCEL = '送信しない'

// 02_note/mail-sending-pitfalls.md: 自治体・学校・小さな組織あては合計2MB以下が目安。gmail-unifierの上限は25MB。
const SMALL_ORG_LIMIT = 2 * 1024 * 1024
const HARD_LIMIT = 25 * 1024 * 1024

const BODY_PREVIEW = 600

type SendArgs = {
  to?: string[] | null
  cc?: string[] | null
  bcc?: string[] | null
  subject?: string
  body?: string | null
  text?: string
  html_body?: string | null
  attachment_paths?: string[] | null
  include_attachments?: boolean
  message_handle?: string
  reply_to_message_handle?: string | null
  reply_all?: boolean
  draft_handle?: string
}

const textOf = (r: McpToolResult) =>
  r.content.map(b => (b.type === 'text' ? b.text : '')).join('\n').trim()

const list = (xs?: string[] | null) => (xs && xs.length > 0 ? xs.join(', ') : undefined)

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n)}…（以下${s.length - n}文字省略）` : s)

const mb = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(1)}MB`

export const register: Register = on => {
  // ボタンで承認された呼び出し。classic.PreToolUse でエンジンの許可確認を省く。
  const approved = new Set<string>()

  // gmail-unifier のサーバー指示「送信前にチャットで許可を取る」を、このダイアログで置き換える。
  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    return {
      sections: [
        ...composed.sections,
        {
          id: 'send-confirm:policy',
          scope: 'session',
          text: 'gmail-unifier の送信系ツール（send_message / send_reply / forward / send_draft）は、呼ぶと send-confirm mod が宛先・件名・本文・添付を示したダイアログで本人の承認を取る。送信内容が固まったら、チャットで事前の許可を求めずにそのまま送信ツールを呼んでよい。拒否された場合は理由に従って直す。',
        },
      ],
    }
  })

  on('tool.call', async ($, e, next) => {
    const tool = String(e.tool)
    const name = tool.slice(PREFIX.length)
    if (!tool.startsWith(PREFIX) || !SEND_TOOLS.has(name)) return next(e)

    const args = e as unknown as SendArgs
    const lines: string[] = []

    if (name === 'send_draft' && args.draft_handle) {
      const draft = await $.mcp.call(SERVER, 'get_draft', { draft_handle: args.draft_handle })
      lines.push('【下書きを送信】', clip(textOf(draft), BODY_PREVIEW * 2))
    } else {
      const origin = args.message_handle ?? args.reply_to_message_handle
      if (origin) {
        const original = await $.mcp.call(SERVER, 'read_message', { message_handle: origin })
        const head = textOf(original).split('\n').slice(0, 4).join(' / ')
        lines.push(`【${name === 'forward' ? '転送' : '返信'}】元メール: ${clip(head, 160)}`)
      }
      const to = list(args.to)
      lines.push(`To: ${to ?? (origin ? '（元メールの差出人）' : '（なし）')}${args.reply_all ? '  ※全員に返信' : ''}`)
      if (list(args.cc)) lines.push(`Cc: ${list(args.cc)}`)
      if (list(args.bcc)) lines.push(`Bcc: ${list(args.bcc)}`)
      if (args.subject) lines.push(`件名: ${args.subject}`)
      const body = args.body ?? args.text ?? args.html_body ?? ''
      lines.push('本文:', clip(body, BODY_PREVIEW))
      if (name === 'forward' && args.include_attachments !== false) lines.push('元メールの添付も付く')
    }

    let total = 0
    for (const path of args.attachment_paths ?? []) {
      const size = await $.fs.stat(path).then(s => s.size, () => undefined)
      if (size === undefined) return { deny: `send-confirm: 添付が見つからない: ${path}` }
      total += size
      lines.push(`添付: ${path.split('/').pop()} (${mb(size)})`)
    }
    if (total > HARD_LIMIT) return { deny: `send-confirm: 添付合計 ${mb(total)} が25MBを超えている。圧縮か分割をする。` }
    if (total > SMALL_ORG_LIMIT) {
      lines.push(`⚠ 添付合計 ${mb(total)}。自治体・学校・小さな組織あては2MB以下が目安（mail-sending-pitfalls.md）`)
    }

    const answer = await $.ui
      .ask(`${lines.join('\n')}\n\nこの内容で送信しますか？`, {
        header: '送信確認',
        options: [SEND, CANCEL],
      })
      .catch(() => CANCEL)

    if (answer !== SEND) {
      const reason = answer === CANCEL ? '本人が送信を取り消した。' : `本人の指示: ${answer}`
      return { deny: `send-confirm: ${reason}` }
    }

    approved.add(e.tool_use_id)
    try {
      return await next(e)
    } finally {
      approved.delete(e.tool_use_id)
    }
  })

  on('classic.PreToolUse', ($, e, next) =>
    approved.has(e.tool_use_id) ? { allow: true } : next(e),
  )
}
