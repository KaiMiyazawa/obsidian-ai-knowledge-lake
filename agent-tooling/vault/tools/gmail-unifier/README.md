# gmail-unifier

個人・大学・インターンなど、複数のGmail / Google Workspaceメールボックスを**直接**検索するローカルMCP。
メールを転送・複製せず、アーカイブ済みメールを含む各メールボックスの正本を読む。

## 重要な性質

- 各アカウントは個別のGoogle OAuthで認可する。メール本文・トークンは保管庫に保存しない。
- OAuthリフレッシュトークンと返信ハンドルの署名鍵はOSの資格情報ストアに保存する（macOSはKeychain、WindowsはCredential Manager）。通常のメール操作でTouch IDを要求する設計ではない。
- メール・スレッド・下書きは、検索や一覧で得た**署名済みハンドル**でだけ指定する。ハンドルにはメールボックスが焼き込まれていて、操作は必ずそのメールボックスに対して行われる。
- 返信・転送（`create_draft` / `send_message` に返信先ハンドルを渡す、`send_reply`、`forward`）は、受信したメールボックスから送られる。`from` は指定できない。新規メールだけ `account_id` で送信元を選ぶ。
- 送信系（`send_draft` / `send_message` / `send_reply` / `forward`）は、AIが送信前に宛先・件名・本文を本人に示し、明示的な許可を得てから呼ぶ。
- **完全削除のツールは作らない。** 削除はゴミ箱への移動（`trash`）だけ。下書きの削除（`delete_draft`）とラベルの削除（`delete_label`）は、Gmailの画面と同じ動き。

## ツール一覧 — Claude の Gmail MCP の全30ツールに対応（2026-10-01）

対応表は `tests/test_server.py` の `GMAIL_MCP_COVERAGE` にあり、テストで欠けがないかを確かめている。
メッセージ用とスレッド用に分かれていた操作は、どちらのハンドルも受け取る1つのツールにまとめた（複数件をまとめて渡せる）。

| 分類 | gmail-unifier | Gmail MCP で対応するもの |
| --- | --- | --- |
| 検索・閲覧 | `list_mailboxes`, `search_mail`（メッセージ単位）, `search_threads`, `read_message`, `get_thread`, `download_attachment` | `search_threads`, `get_message`, `get_thread` |
| ラベル | `list_labels`, `create_label`, `update_label`, `delete_label`, `modify_labels` | `list_labels`, `create_label`, `update_label`, `delete_label`, `label_*`, `unlabel_*`, `update_message_labels` |
| ゴミ箱・迷惑メール | `trash`, `untrash`, `mark_spam`, `unmark_spam` | `trash_*`, `untrash_*`, `mark_*_spam`, `unmark_*_spam`, `apply_sensitive_*_label` |
| 下書き | `list_drafts`, `get_draft`, `create_draft`, `create_reply_draft`, `update_draft`, `delete_draft` | `list_drafts`, `get_draft`, `create_draft`, `update_draft`, `delete_draft` |
| 送信 | `send_draft`, `send_message`, `send_reply`, `forward` | `send_message`, `reply`, `forward` |

Gmail MCP との違い:

- `read_message` / `get_thread` / `get_draft` の `format` は `metadata` / `minimal` / `plain`（既定） / `full` / `raw`。
- 添付は base64 ではなく**ローカルファイルのパス**で渡す（`attachment_paths`、合計25MBまで）。受け取りは `download_attachment` で `~/Downloads/gmail-unifier/` に保存する。
- `update_draft` は、`attachment_paths` を渡さなければ既存の添付を残す（Gmail MCP は消える）。
- `forward` は元メールの添付も既定で付ける。
- ラベルの色は `red` / `blue` などの名前で指定する（Gmail MCP の color preset と同じ21色）。

## 開発状態

初期実装。Google Cloudプロジェクト `gmail-unifier` のDesktop OAuthクライアントは作成済み（2026-09-24）。
macOSでは個人・会社・大学の3アカウントをOAuth認可し、Gmail APIのプロフィール照会を検証済み。
横断検索で各アカウント1件ずつ結果を取得し、アーカイブ検索も各アカウントで1件以上ヒット。各1件の本文読取APIが応答することも確認したが、件名・本文は表示・保存していない。返信下書きの作成・送信は、実メールボックスを変更するため未実施。
`read_message` の本文は `text/plain` を優先し、無ければ `text/html` をテキスト化して返す（リンクURLは `<URL>` で残す）。文字コードは各パートの `charset` に従う（2026-09-28、HTMLのみのメールで本文が空になる不具合を修正）。
CodexとClaude Codeのユーザー設定へMCPを登録済み。利用開始時に両クライアントを再起動し、`list_mailboxes`で接続を確認する。

## セットアップ（各OSで1回）

1. Google Cloudで専用プロジェクトを作成し、Gmail APIを有効化する。
2. OAuth同意画面を「外部・テスト」にし、利用するGoogleアカウントをテストユーザーに追加する。
3. Desktop app OAuth clientを作り、ダウンロードしたJSONを保管庫の外に置く。
4. `config.example.toml` をOSごとの設定パスへコピーし、メールアドレスを実値にする。
5. 依存関係を導入後、各メールボックスを認可する。

```bash
uv sync --group dev
uv run gmail-unifier authorize personal --client-secrets /安全な場所/client_secret.json
uv run gmail-unifier authorize company --client-secrets /安全な場所/client_secret.json
uv run gmail-unifier authorize univ --client-secrets /安全な場所/client_secret.json
```



## Codex / Claude Codeへの登録

登録設定には秘密を含めない。`--config` は各OSの保管庫外設定ファイルを指す。

```toml
[mcp_servers.gmail-unifier]
command = "/絶対パス/gmail-unifier/.venv/bin/gmail-unifier"
args = ["--config", "/Users/you/.config/gmail-unifier/config.toml", "serve"]
```

Windowsでは、同じ構成をWindows側の絶対パスに置き換える。Claude Codeも同じstdioコマンドをユーザースコープで登録する。

## 運用上の制約

- 学校・インターン先が第三者OAuthアプリを禁止している場合、そのアカウントは認可しない。
- 既存Gmailコネクタは、このMCPの利用開始後に切断する必要はない。ただしメール横断照会は `gmail-unifier` を正とする。
- 認可範囲は `https://mail.google.com/`（全権限）。2026-10-01、再認可を最後にするために本人が選んだ。
  ツールとしては完全削除を提供しないので、範囲が広くても事故で消えることはない。
  旧トークン（`gmail.readonly` + `gmail.compose`）のままでも読み取りは動き、書き込み系だけが権限不足で失敗する。
  `gmail-unifier status` で、各アカウントが全権限か（`[全権限]` / `[要再認可]`）を確認できる。
- OAuth同意画面が「テスト」のままだと、リフレッシュトークンが7日で失効する（[Google の説明](https://developers.google.com/identity/protocols/oauth2)、2026-10-01確認）。
  本番環境（未確認アプリ）に切り替えて避ける。認可時に「Googleが確認していないアプリ」の警告が出るので、詳細→続行で進む。

## 関連

- [`../../02_note/mcp-inventory.md`](../../02_note/mcp-inventory.md): 接続済みMCPの一覧
- [`../../02_note/services-accounts.md`](../../02_note/services-accounts.md): サービスとアカウントの対応表
- [`../../02_note/mail-sending-pitfalls.md`](../../02_note/mail-sending-pitfalls.md): メール送信で失敗した原因と確認手順
