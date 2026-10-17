# AI エージェント用の自作ツール一式

Obsidian 保管庫で Claude Code と Codex を使うための、自作のスキル・MCP・mod・フック・CLI をまとめたもの。

## 使い方

1. このリポジトリをクローンする（保管庫の外でよい）。
2. 保管庫で Claude Code か Codex を開き、次のように頼む:
   > `<展開した場所>/agent-tooling/FOR_AI.md` を読んで、この道具を私の保管庫に入れるのを手伝って
3. AI が、使う AI・OS・入れたい道具などを聞いてくるので答える。

## 中身

- `FOR_AI.md` … AI 向けの説明（導入の手順・決まり・注意点）
- `vault/` … 保管庫の中に置くもの（スキル、判断基準のひな形、`tools/`、フックの設定）
- `vault/02_note/agent-tooling.md` … 道具の一覧と、Claude と Codex のどちらで使えるか
- `outside-vault/` … 保管庫の外に置くもの（`gtasks-mcp`、`transcripter`、`daily-digest`、`/gemini-search`）

元の持ち主の個人情報（メールアドレス・ID・名前など）は伏せ字にしてあり、秘密の値は入っていない。
Google アカウントとの連携（OAuth）には、自分で作った Google Cloud のプロジェクトが要る。手順は AI が案内する。
