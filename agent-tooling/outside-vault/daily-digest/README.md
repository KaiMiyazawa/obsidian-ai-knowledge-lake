# daily-digest — 朝のダイジェストと月初のお金チェック

Mac の launchd から `codex exec`（Codexの非対話実行）を起動し、結果を Discord（自分のサーバーの `#digest`）に送る。

| 種類 | 起動 | プロンプト | 中身 |
| --- | --- | --- | --- |
| 朝のダイジェスト | 毎日 7:30（Mac が寝ていれば起きたとき） | `morning.md` | 今日の予定・7日以内の大事な予定・期限切れタスク・要対応メール |
| お金チェック | 毎月1日 9:00 | `money.md` | 今月出す請求・前月の入金・今月の支払いと期限・年収の壁・月次の提出物 |

- **モデルを用途別に指定する。** 朝は `gpt-6.1-sol / medium`、月初のお金チェックは同モデルの `high`。Codexのログイン済みアカウントの利用枠を使い、対話セッションの既定には依存しない。
- **読み取り専用。** `codex_digest.py` が `codex exec --ephemeral --sandbox read-only` を呼ぶ。シェル・JS・Web検索を無効化し、Tasks・gmail-unifier・会計MCPとCalendarアプリの読み取りツールだけを許可。月初に必要なローカル資料はランナーが読み込んで渡す。他のMCP・プラグイン・アプリはこの実行だけ無効にする。
- Calendarには `features.apps=true` と `google_calendar.list_calendars` など実際のツール名の許可が必要。保管庫の会計MCP設定も使うため、作業ディレクトリは `~/Desktop/Obsidian`。
- JSONLの最終応答だけを送信対象にする。900秒のタイムアウト、失敗・見出し欠落・1800文字超過では送信せず、死活監視へ失敗を通知する。詳細なツール応答・資格情報はログへ出さない。既存ログには種類・モデル・effort・終了コード・経過秒を出す。
- メール・予定・会計の要約が Discord に載る。**本人が 2026-10-02 に、この送信を明示的に決めた。**
- 死活監視は Healthchecks.io のチェック `morning-digest`（cron `30 7 * * *`、猶予6時間）と `money-check`（cron `0 9 1 * *`、猶予1日）。
  失敗や未実行は `#urgent` に届く。全体像は保管庫の `02_note/notification-bots.md`。

## 試す

```bash
./digest.zsh morning --dry-run   # 送らずに標準出力へ
./digest.zsh money --dry-run
```

## 入れ方（本人が行う。Claude の自動実行では LaunchAgent の登録と秘密の値の設定が止められる）

1. `~/.config/notify/daily-digest.env`（`chmod 600`）を作る:
   ```
   WEBHOOK_URL=<自分のサーバーの #digest の Webhook「digest」>
   HC_URL_MORNING=https://hc-ping.com/<Ping key>/morning-digest
   HC_URL_MONEY=https://hc-ping.com/<Ping key>/money-check
   ```
2. LaunchAgent を登録する:
   ```bash
   cp launchd/*.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.daily-digest.morning.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.daily-digest.money.plist
   ```
3. その場で1回送るなら `launchctl kickstart gui/$(id -u)/com.example.daily-digest.morning`。ログは `~/Library/Logs/com.example.daily-digest.*.log`。

止めるときは `launchctl bootout gui/$(id -u)/com.example.daily-digest.morning`（money も同様）。
