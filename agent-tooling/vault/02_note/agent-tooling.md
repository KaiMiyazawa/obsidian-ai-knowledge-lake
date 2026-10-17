---
icon: 🧰
visibility: private
created: 2026-10-16
updated: 2026-10-16
---

# 自作の AI エージェント用ツール一覧

**Claude Code・Codex に持たせている自作（と改造）の道具を、1か所で見渡すための索引。**
中身・経緯・判断は各ノートや README が原本。ここには「何があり、どこにあり、どこを読めば分かるか」だけを置く。
道具を足したり消したりしたら、この表も直す。

- 外部の MCP を含む接続先の全体と、入れないと決めたもの → [`mcp-inventory.md`](./mcp-inventory.md)
- どの AI がどのアカウントに繋がっているか → [`services-accounts.md`](./services-accounts.md)
- 使い分けの原則: MCP → ブラウザ → Codex computer-use の順

## 全体の形

| 種類 | 何をするものか | 置き場所 | Claude | Codex |
| --- | --- | --- | --- | --- |
| **スキル（コマンド）** | `/inbox` のように呼ぶ手順書。判断基準は別のノートに分けて置く | `.claude/skills/<名前>/SKILL.md` | ○（この保管庫） | ×（Codex のスキルとしては登録していない） |
| **MCP** | AI から外部サービスを直接触るためのサーバー | `tools/` か `~/Documents/<名前>/` | ○（`~/.claude.json`） | ○（`~/.codex/config.toml`） |
| **mod** | Claude Code の中に処理を差し込むプラグイン（パネル・確認画面・ガード） | `tools/claude-mods/` | ○（ユーザー単位） | ×（一部はフックで代わりにしている） |
| **フック** | 起動時・ツール実行前に決まった処理を走らせる | `.claude/settings.json` / `.codex/hooks.json` | ○ | ○（中身は別。下の表） |
| **CLI・スクリプト** | AI が Bash から呼ぶ自作ツール | `tools/` / `~/Documents/<名前>/` | ○ | ○ |

**○ = いまの設定でそのまま使える、× = 使えない。** 2026-10-16 に `~/.claude.json`・`~/.codex/config.toml`・`.codex/config.toml`・`~/.codex/skills/` を見て確かめた。

## スキル（`/コマンド名` で呼ぶ）

**スキルはすべて Claude Code 専用。** Codex のスキル置き場（`~/.codex/skills/`）にも保管庫にも、Codex 向けには登録していない。

| コマンド | 何をするか | 判断基準・原本 |
| --- | --- | --- |
| `/inbox` | 複数アカウントの Gmail を仕分ける。アーカイブ・下書き・タスク化などを提案し、Yes/No で承認を取ってから実行 | [`mail-triage-rules.md`](./mail-triage-rules.md) |
| `/slack` | Slackの自分宛て DM・メンションに、無視・リアクション・返信を提案 | [`chat-triage-rules.md`](./chat-triage-rules.md) |
| `/discord` | Discord の未読に同じことをする（ブラウザで読む） | [`chat-triage-rules.md`](./chat-triage-rules.md)、[`discord-access.md`](./discord-access.md) |
| `/prioritize` | Google Tasks の並び替えとスター。`all` で project・main・big・agents をまとめて扱う。親タスク名を渡すとサブタスクを手順の順に並べ直す | [`task-priority-rules.md`](./task-priority-rules.md) |
| `gtasks-ui` | Google Tasks の API に無い操作（スター・開始時刻・繰り返し）をブラウザで行う。ほかのスキルからも呼ばれる | [`mcp-inventory.md`](./mcp-inventory.md) の Google Tasks の節 |
| `transcripter` | 文字起こし・字幕・PDF→Markdown・動画の内容把握を、下の `transcripter` で行う（Codex は CLI を直接呼べばよい） | [`transcripter.md`](./transcripter.md) |

- `/inbox`・`/slack`・`/discord`・`/prioritize` は同じ形で作っている: **集める（読むだけ）→ Yes/No で提案 → 承認されたものだけ実行 → 本人が直した内容を基準ノートに追記して育てる。** 新しいスキルを作るときもこの形にそろえる。
- 上流から複製しただけのスキル（`obsidian-markdown`・`obsidian-bases`・`defuddle`）は自作ではない。取得元と更新の仕方は [`../AGENTS.md`](../AGENTS.md)「エージェント用スキル」に書いてある。
- ユーザー単位のコマンド `~/.claude/commands/gemini-search.md`（`/gemini-search`、Gemini CLI で Web 検索）もある。これも Claude 専用。

## MCP

| MCP | 自作か | 何ができるか | ソース | Claude | Codex | 原本 |
| --- | --- | --- | --- | --- | --- | --- |
| **`gmail-unifier`** | 自作 | 複数アカウントの Gmail を、転送せず直接 OAuth で横断検索する。読む・下書き・送信・ラベル・ゴミ箱まで（完全削除だけは作っていない） | [`../tools/gmail-unifier/`](../tools/gmail-unifier/README.md) | ○（送信は `send-confirm` のダイアログで承認） | ○（送信系4つは `.codex/config.toml` で毎回承認。Codex から実際に送れるかは未確認） | 同 README、[`mcp-inventory.md`](./mcp-inventory.md) |
| **`gtasks`** | 改造版（上流 `alvinjchoi/gtasks-mcp`） | Google Tasks API v1 の全操作。上流に無かった取得・リスト作成・位置指定・絞り込み・`web:` リンクを足し、出力を短くしてある | `~/Documents/gtasks-mcp`（GitHub 非公開） | ○ | ○ | [`mcp-inventory.md`](./mcp-inventory.md) |

ほかの MCP（Calendar・Drive・Slack・マネーフォワード・1Password Environments・TradingView など）は外部のもの。一覧は [`mcp-inventory.md`](./mcp-inventory.md)。

## mod（Claude Code のみ。Codex では使えない）

| mod | 何をするか |
| --- | --- |
| `vault-guard` | 公開領域（`99_public/`・`89_profile/`）に非公開ノートへの参照を書こうとしたら止める。カレンダーの色ルール違反も止める |
| `send-confirm` | `gmail-unifier` の送信の直前に、宛先・件名・本文・添付を見せる確認画面を出す |
| `tasks-pane` | Google Tasks の5リストを横のパネルに出す（`/todo`）。Enter で着手の依頼文を入力欄に入れる |
| `status-band` | 入力欄の上に、モデル・文脈の使用率・利用枠・Cloud クレジットの残り日数を出す |
| `git-guard` | `git add`/`commit` の前に取り込み、ステージを戻す。削除を巻き込む一括ステージや force push を止める |

詳細と Codex 側で代わりにしているもの → [`claude-code-mods.md`](./claude-code-mods.md)。ソースは [`../tools/claude-mods/`](../tools/claude-mods/README.md)。

## フック

| AI | いつ | 何をするか | 設定 |
| --- | --- | --- | --- |
| Claude | セッション開始時 | Google Tasks `agents` を読み込んで文脈に入れる | `.claude/settings.json` |
| Codex | セッション開始時 | 同じく `agents` を読み込む。親と3つのサブモジュールを fetch して、遅れているかを伝える | `.codex/hooks.json` |
| Codex | ツール実行前 | `vault-guard`・`git-guard` 相当の検査、メール添付の検査 | `.codex/hooks.json` → [`../tools/codex-hooks/`](../tools/codex-hooks/README.md) |

## CLI・スクリプト（AI が Bash から呼ぶ）

**どれも Bash から呼ぶだけなので、Claude・Codex のどちらからでも使える。**

| ツール | 何をするか | 置き場所 | 原本 |
| --- | --- | --- | --- |
| `transcripter` | ローカルで文字起こし・字幕・PDF→Markdown・動画ダイジェスト（静止画＋発話）を作る。外部へは送らない | `~/Documents/transcripter`（GitHub 非公開） | [`transcripter.md`](./transcripter.md) |
| `1password-ai-op.zsh` | Service Account 経由で `AI-Managed` Vault を読み書きする。トークンは保管庫やチャットに残さない | [`../tools/1password-ai-op.zsh`](../tools/1password-ai-op.zsh) | [`1password.md`](./1password.md) |
| `1password-weak-password-audit*.zsh` | 1Password の弱いパスワードを点検する | `tools/` | [`1password.md`](./1password.md) |
| `chat-recovery` | ChatGPT・Codex・Claude の過去の会話から、保存していない知識を回収するための台帳を作る | [`../tools/chat-recovery/`](../tools/chat-recovery/README.md) | [`ai-chat-recovery/`](./ai-chat-recovery/README.md) |
| `fill_ta_sheet.py` | 大学の TA の出勤表（Excel）に1か月分を書き込む（図形を消さないよう XML を直接書き換える） | [`../tools/ta-attendance/`](../tools/ta-attendance/fill_ta_sheet.py) | — |
| Discord アーカイブ（自作拡張＋巡回） | Discord の過去ログを貯める | `78_discord_archive/` | [`../78_discord_archive/README.md`](../78_discord_archive/README.md) |

## AI を自動で動かしているもの

**どちらも Codex（`codex exec`）で動かしている。** Claude では動かしていない。

| 名前 | 何をするか | 原本 |
| --- | --- | --- |
| 朝のダイジェスト | 毎朝 7:30、launchd が `codex exec` を読み取り専用で起動し、予定・タスク・要対応メールを Discord `#digest` に送る | [`notification-bots.md`](./notification-bots.md) |
| 月初のお金チェック | 毎月1日 9:00、同じ仕組みで請求・入金・支払い・年収の壁を送る | [`notification-bots.md`](./notification-bots.md) |

AI を使わない監視 bot（ディスク・EC2 など）は [`notification-bots.md`](./notification-bots.md) にまとめてある。

## 新しく作るときの決まり

- **作る前に、MCP で届くかを見る。** 両方から届くなら MCP を使う（ブラウザより文脈の消費が桁違いに少ない）。AGENTS.md「手段の選び方」。
- **スキルは「手順」と「判断基準」を分ける。** 基準は `02_note/*-rules.md` に置き、本人が直した内容をそこに追記する。
- **独立したリポジトリになるもの**（`node_modules`・`.venv` を持つもの）は `~/Documents/<名前>/` に置き、保管庫には判断と参照だけを残す（AGENTS.md「開発中のコードとデータ」）。
- **秘密の値は保管庫・Git・チャットに置かない。** トークンは Keychain や `~/.<ツール名>/` に置く。
- 作ったらこのノートの表に1行足し、AGENTS.md のスキル一覧など関係する索引も直す。
