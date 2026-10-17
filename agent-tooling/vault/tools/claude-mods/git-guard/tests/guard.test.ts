import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'

const ROOT = '/v'

type Repo = { behind: number; staged: string[]; unstaged: string[]; status: string[] }

// git の呼び出しを、引数ごとに決め打ちで答える。
const fakeGit = (repo: Repo, calls: string[][]) => ($: unknown, e: { argv: readonly string[] }) => {
  const args = e.argv.slice(1)
  calls.push([...args])
  const out = (stdout: string, exitCode = 0) => ({ value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  const z = (xs: string[]) => xs.map(x => `${x}\0`).join('')
  switch (args[0]) {
    case 'rev-parse':
      return out(`${ROOT}\n`) as never
    case 'rev-list':
      return out(`${repo.behind}\n`) as never
    case 'diff':
      return out(z(args.includes('--cached') ? repo.staged : repo.unstaged)) as never
    case 'status':
      return out(z(repo.status)) as never
    default:
      return out('') as never
  }
}

const setup = (on: On, repo: Repo) => {
  const calls: string[][] = []
  on('session.root', () => ({ value: ROOT }) as never)
  on('env.get', () => ({ value: '/home' }) as never)
  on('process.run', fakeGit(repo, calls) as never)
  on('tool.call', () => ({ result: 'ok' }) as never)
  return calls
}

test('遅れていれば commit の前に pull し、ステージを戻す', async ($, on) => {
  const calls = setup(on, { behind: 2, staged: ['a.md'], unstaged: [], status: [] })
  const r = await $.tool.call({ tool: 'Bash', command: 'git commit -m "x"' })
  expect(r.deny).toBeUndefined()
  expect(calls.some(c => c[0] === 'pull' && c.includes('--autostash'))).toBe(true)
  expect(calls.some(c => c[0] === 'add' && c.includes('a.md'))).toBe(true)
  expect(r.context?.join('')).toContain('2コミット')
})

test('一部だけステージしたファイルがあれば pull せずに止める', async ($, on) => {
  const calls = setup(on, { behind: 1, staged: ['a.md'], unstaged: ['a.md'], status: [] })
  const r = await $.tool.call({ tool: 'Bash', command: 'git commit -m "x"' })
  expect(r.deny).toContain('一部だけステージ')
  expect(calls.some(c => c[0] === 'pull')).toBe(false)
})

test('git add -A が削除を巻き込むなら止める', async ($, on) => {
  setup(on, { behind: 0, staged: [], unstaged: [], status: [' D 01_diary', ' M note.md'] })
  const r = await $.tool.call({ tool: 'Bash', command: 'git add -A && git commit -m x' })
  expect(r.deny).toContain('01_diary')
})

test('削除がなければ git add -A は通す', async ($, on) => {
  setup(on, { behind: 0, staged: [], unstaged: [], status: [' M note.md'] })
  const r = await $.tool.call({ tool: 'Bash', command: 'git add -A' })
  expect(r.deny).toBeUndefined()
})

test('force push は止める', async ($, on) => {
  setup(on, { behind: 0, staged: [], unstaged: [], status: [] })
  const r = await $.tool.call({ tool: 'Bash', command: 'git push --force origin main' })
  expect(r.deny).toContain('force push')
})
