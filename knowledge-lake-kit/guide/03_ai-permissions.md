# AI に何を許可し、何を止めているか

## 考え方

- **読み取りは自由に、書き込みは確認付きで。** 読み取り（検索・閲覧・一覧）は確認なしで通るように許可リストに入れる。毎回の確認ダイアログは注意力を削り、本当に危ない確認を読み飛ばす原因になる。
- **取り返しのつかない操作は、指示と仕組みの二重で止める。** `AGENTS.md` に書くだけでなく、承認設定・フックでも止める。
- **自分のアカウントで行うことは AI がやってよい範囲を決めておく。** 例えばログイン・認証は「計画段階で、対象サービス・アカウント・認証方法・理由を示せば AI が行ってよい」と決めた。ただしログインの許可は、その後の送信・購入・削除の許可を兼ねない。

## 許可していること / 確認を取ること / させないこと

| 区分 | 例 |
| --- | --- |
| **確認なしで通す** | 保管庫の読み書き、メール・予定・ドライブ・Slack の検索と閲覧、タスクの作成と更新、ブラウザでのページ読み取り、`git pull --rebase --autostash` |
| **実行前に内容を見せて承認** | メール送信、予定の作成・変更（招待が飛ぶ）、ファイル共有の変更、会計など業務データの書き込み、公開サイトへの反映、購入 |
| **させない** | force push、一括削除、パスワード・秘密の値を保管庫やチャットに書き写す、非公式の「全パスワードにアクセスできる」系ツールの導入、支払い・送金の実行 |

メール送信のように頻度が高く危ないものは、送信直前に宛先・件名・本文・添付を並べた確認ダイアログを出す仕組み（Claude Code の mod / Codex の承認設定）を入れている。

## Codex の設定例

`.codex/config.toml`（保管庫だけに効く）:

```toml
project_doc_max_bytes = 65536   # AGENTS.md が32KiBを超えても末尾まで読ませる

[features]
hooks = true

# 送信系ツールは毎回承認
[mcp_servers.<メールのMCP>.tools.send_message]
approval_mode = "prompt"

# サーバー全体は「書き込みだけ承認」
[mcp_servers.<会計などのMCP>]
default_tools_approval_mode = "writes"
```

フック（`.codex/hooks.json` と `tools/codex-hooks/guard.py`）:
- 起動時に Git の遅れを知らせる
- `git add` / `commit` の前に自動で `git pull --rebase --autostash`
- force push・削除を含む一括ステージ・公開フォルダへの非公開参照を拒否

## Claude Code の設定例

`.claude/settings.json`（保管庫だけに効く。Git 管理する）。**接続していない MCP の行は書かない。**

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": [
      "mcp__<Gmail系>__search_*",
      "mcp__<Gmail系>__read_*",
      "mcp__<Drive系>__search_*",
      "mcp__<Drive系>__read_*",
      "mcp__<Calendar系>__list_*",
      "mcp__<Calendar系>__get_*",
      "mcp__<Tasks系>__list*",
      "mcp__<Tasks系>__get*",
      "mcp__<Tasks系>__create",
      "mcp__<Tasks系>__update",
      "mcp__claude-in-chrome__navigate",
      "mcp__claude-in-chrome__get_page_text",
      "mcp__claude-in-chrome__read_page",
      "mcp__claude-in-chrome__find",
      "mcp__claude-in-chrome__tabs_context_mcp",
      "Bash(git pull --rebase --autostash)"
    ],
    "ask": [
      "Read(./30_study/**/answers/**)"
    ]
  }
}
```

- `allow` は読み取り系とタスク操作だけ。送信・削除系は入れない（毎回聞かれる状態のまま）。
- `ask` は「読まれると困るもの」を確認付きにする使い方もできる（例: 自力で解きたい課題の解答フォルダ）。
- 端末ごとの設定は `.claude/settings.local.json`（Git 管理外）へ。
- ルートの `CLAUDE.md` は `@AGENTS.md` の1行だけにし、指示書を `AGENTS.md` に一本化する。

## 秘密の値

- パスワード・APIキーは、パスワードマネージャーに置く。保管庫・Git・チャットに書かない。ノートには「どの項目に入っているか」だけ書く。
- AI にパスワードマネージャーのマスターパスワードを渡さない。ブラウザ操作でのログインは、ブラウザの自動入力に任せる。
