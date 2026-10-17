import type { EngineInterface, Register } from 'claude-code'

// AGENTS.md「Git 運用」を機械的に守らせる。
// - add / commit の前に fetch し、遅れていれば pull --rebase --autostash する。
//   autostash はステージを外す（2026-10-05 に確認）ので、ステージ済みのパスは pull 後に add し直す。
// - add -A / add . / commit -a で削除（サブモジュールのポインタ削除を含む）を巻き込むときは止める。
// - force push は止める。
// - 起動時に親と3つのサブモジュールを fetch し、遅れを状態行に出す（pull はしない）。

const SUBMODULES = ['01_diary', '89_profile/github-profile', '99_public']
const FETCH_TTL_MS = 60 * 1000

const GIT = String.raw`\bgit(?:\s+-C\s+\S+)?\s+`
const ADD = new RegExp(`${GIT}add\\b`)
const COMMIT = new RegExp(`${GIT}commit\\b`)
const ADD_ALL = new RegExp(`${GIT}add\\b[^;&|]*\\s(?:-A|--all|\\.)(?=\\s|$|;|&|\\|)`)
const COMMIT_ALL = new RegExp(`${GIT}commit\\b[^;&|]*\\s(?:-[a-zA-Z]*a[a-zA-Z]*|--all)(?=\\s|$)`)
const FORCE_PUSH = new RegExp(`${GIT}push\\b[^;&|]*\\s(?:-f|--force\\S*)(?=\\s|$)`)
const GIT_ANY = new RegExp(`${GIT}(?:pull|push|commit|fetch|merge|rebase|submodule)\\b`)
const C_DIR = /\bgit\s+-C\s+("[^"]+"|'[^']+'|\S+)/
const CD_DIR = /^\s*cd\s+("[^"]+"|'[^']+'|\S+)\s*&&/

const unquote = (s: string) => s.replace(/^["']|["']$/g, '')

type Sync = { deny: string } | { note?: string }

// モジュールの変数なので、ホットリロードで消える（次の fetch が走るだけ）。
const fetchedAt = new Map<string, number>()

const git = ($: EngineInterface, cwd: string, args: string[], timeoutMs = 30_000) =>
  $.process.run(['git', ...args], { cwd, timeoutMs })

const lines = (s: string) => s.split('\0').filter(Boolean)

const behind = async ($: EngineInterface, repo: string, force: boolean) => {
  const last = fetchedAt.get(repo) ?? 0
  if (force || Date.now() - last > FETCH_TTL_MS) {
    const f = await git($, repo, ['fetch', '--quiet'])
    if (f.exitCode !== 0) return undefined
    fetchedAt.set(repo, Date.now())
  }
  const c = await git($, repo, ['rev-list', '--count', 'HEAD..@{u}'])
  return c.exitCode === 0 ? Number(c.stdout.trim()) : 0
}

const sync = async ($: EngineInterface, repo: string): Promise<Sync> => {
  const n = await behind($, repo, false)
  if (n === undefined) return { note: 'git-guard: fetch に失敗した（オフライン？）。pull せずに進めた。push 前に取り込む。' }
  if (n === 0) return {}

  const staged = lines((await git($, repo, ['diff', '--cached', '--name-only', '-z'])).stdout)
  const unstaged = new Set(lines((await git($, repo, ['diff', '--name-only', '-z'])).stdout))
  const partial = staged.filter(p => unstaged.has(p))
  if (partial.length > 0) {
    return {
      deny: `git-guard: リモートが${n}コミット進んでいるので取り込みが必要だが、一部だけステージしたファイルがあり、pull --rebase --autostash でステージが崩れる: ${partial.slice(0, 5).join(', ')}。先に git pull --rebase --autostash してからステージし直す。`,
    }
  }

  const pull = await git($, repo, ['pull', '--rebase', '--autostash'], 120_000)
  if (pull.exitCode !== 0) {
    return {
      deny: `git-guard: git pull --rebase --autostash が失敗した。git status で状態を確認し、競合は本人と相談して解く（--force や reset --hard はしない）。\n${(pull.stderr || pull.stdout).slice(0, 800)}`,
    }
  }
  if (staged.length > 0) await git($, repo, ['add', '-A', '--', ...staged])

  return { note: `git-guard: リモートの${n}コミットを pull --rebase --autostash で取り込んだ${staged.length > 0 ? '（ステージは復元済み）' : ''}。` }
}

const deletions = async ($: EngineInterface, repo: string) => {
  const out = lines((await git($, repo, ['status', '--porcelain=v1', '-z', '--no-renames'])).stdout)
  return out.filter(entry => entry[0] === 'D' || entry[1] === 'D').map(entry => entry.slice(3))
}

const showStatus = async ($: EngineInterface, root: string, force: boolean) => {
  const parts: string[] = []
  for (const [label, path] of [['保管庫', root], ...SUBMODULES.map(s => [s, `${root}/${s}`])] as const) {
    const n = await behind($, path, force).catch(() => 0)
    if (n === undefined) parts.push(`${label} fetch失敗`)
    else if (n > 0) parts.push(`${label} ${n}遅れ`)
  }
  $.ui.status(parts.length > 0 ? `git: ${parts.join(' / ')}` : undefined)
}

const repoOf = async ($: EngineInterface, command: string, root: string) => {
  const dir = unquote(command.match(C_DIR)?.[1] ?? command.match(CD_DIR)?.[1] ?? '.')
  const home = (await $.env.get('HOME')) ?? ''
  const abs = dir.startsWith('/') ? dir : dir.startsWith('~') ? home + dir.slice(1) : `${root}/${dir}`
  const top = await git($, abs, ['rev-parse', '--show-toplevel']).catch(() => undefined)
  if (top === undefined || top.exitCode !== 0) return undefined
  const repo = top.stdout.trim()
  return repo === root || repo.startsWith(`${root}/`) ? repo : undefined
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    const root = await $.session.root()
    void showStatus($, root, true)

    return started
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const command = e.command
    if (FORCE_PUSH.test(command)) {
      return { deny: 'git-guard: force push はしない（AGENTS.md「Git 運用」）。拒否されたら取り込んでからやり直す。' }
    }

    const root = await $.session.root()
    const isStaging = ADD.test(command) || COMMIT.test(command)
    const repo = isStaging ? await repoOf($, command, root) : undefined
    let note: string | undefined

    if (repo !== undefined) {
      const synced = await sync($, repo)
      if ('deny' in synced) return synced
      note = synced.note

      if (ADD_ALL.test(command) || COMMIT_ALL.test(command)) {
        const deleted = await deletions($, repo)
        if (deleted.length > 0) {
          return {
            deny: `git-guard: 一括ステージに削除が含まれる: ${deleted.slice(0, 10).join(', ')}${deleted.length > 10 ? ` ほか${deleted.length - 10}件` : ''}。自分が消したものか確かめ、意図した削除ならパスを個別に指定して git add する（AGENTS.md「Git 運用」）。`,
          }
        }
      }
    }

    const ran = await next(e)
    if (repo !== undefined || GIT_ANY.test(command)) void showStatus($, root, false)
    if (note === undefined || 'deny' in ran) return ran

    return { ...ran, context: [...(ran.context ?? []), note] }
  })
}
