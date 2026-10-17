# Codex guards

Claude modから移植した、この保管庫のCodex用Hooks。設定は [`../../.codex/hooks.json`](../../.codex/hooks.json)、実装は [`guard.py`](guard.py)。Python標準ライブラリのみ使用する。
機能・導入判断の原本は [`../../02_note/claude-code-mods.md`](../../02_note/claude-code-mods.md)。

## 有効化

このMacの保管庫でCodexを開き、CLIの `/hooks` で新規の `SessionStart` と `PreToolUse` を確認して信頼する。定義を変更した場合は再確認が必要。
既存のGoogle Tasks取得は別ハンドラーとして保持している。ユーザー設定の `trusted_hash` を手で書き換えたり、信頼確認を迂回するフラグは使わない。
現在のセッションには自動反映を前提にせず、信頼後に保管庫で新しいセッションを開始する。

## 動作

- `SessionStart`: 親と3サブモジュールを並列にfetchし、遅れをモデルへ返す。pullはしない。
- `vault-guard`: `apply_patch`の公開領域への追加行を検査する。カレンダーのピーコック(7)、終日の日付形式、色なしの初回作成を止める。Codexのコネクタでは終日に `start_date/end_date` を使う。
- `git-guard`: 単独の `git add/commit` の前に `git pull --rebase --autostash`。すでにステージしたパスを取り込み後に復元する。一部だけステージしたファイルがある場合、pull失敗、競合が残る場合は止める。一括ステージに削除が含まれる場合とforce pushも止める。Gitの検査対象は保管庫とその配下のrepo。force push拒否はこのプロジェクトのセッション内の全Git操作に適用する。
- `send-check`: `gmail-unifier`の送信系4ツールで、添付の存在と合計25MB上限を検査する。2MB超はモデルへ注意を返す。チャットで宛先・件名・本文・添付を提示して本人の送信許可を得る運用を維持し、さらにプロジェクト設定で通常のツール承認を必須にしている。返信・転送の元メールや下書き内の添付はモデルが読み取って確認する。

色なし再実行の判定は、セッションIDと引数のハッシュだけをOSの一時ディレクトリに保存する。メール本文・予定・資格情報は保存しない。

## 検証

```sh
python3 -m unittest discover -s tools/codex-hooks -v
```

人工入力と一時的なローカルGitリモートで検証する。実際のメール送信・予定作成・保管庫へのpullはテストでは実行しない。

Hooksは万能な強制境界ではない。シェルや任意のスクリプトによるファイル書き込み、ブラウザ操作などは公開参照検査の対象外。Gitは一般的な単独コマンドと `git -C` に対応し、解析できないラッパーや複合ステージ操作を拒否する。フックのタイムアウトや起動失敗自体はCodex側で実行を通す場合があるため、AGENTS.mdの運用ルールも維持する。

公式仕様（2026-10-06確認）: <https://learn.chatgpt.com/docs/hooks>
