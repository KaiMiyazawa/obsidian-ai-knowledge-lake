# Codex guards

保管庫用の Codex Hooks。設定は [`../../.codex/hooks.json`](../../.codex/hooks.json)、実装は [`guard.py`](./guard.py)。Python 標準ライブラリのみ。

## 何をするか

- **起動時**: 保管庫（とサブモジュール）を fetch して、リモートより何コミット遅れているかを AI に伝える。pull はしない。
- **`git add` / `git commit` の直前**: `git pull --rebase --autostash` で取り込み、すでにステージしていたものを戻す。
  スマホなど別の場所でリモートが進んでいても、古い状態にコミットを積まない。
- **force push を拒否**する。
- **`git add -A` などの一括ステージに削除が含まれていたら拒否**する（意図しない削除の巻き込み防止）。
- **公開フォルダ（`89_profile/`・`99_public/`）に、非公開フォルダへの参照を書き足すのを拒否**する。

## 有効化

1. `../../.codex/hooks.json` の `__VAULT_ROOT__` を保管庫の絶対パスに置き換える。
2. `guard.py` 冒頭の `PUBLIC_AREAS`・`PRIVATE_PATTERNS` を保管庫の構成に合わせる。
3. テスト: `python3 -m unittest discover -s tools/codex-hooks -v`
4. Codex の `/hooks` で新しいフックを確認し、**本人が**信頼する。信頼確認を迂回しない。

Hooks は万能な強制境界ではない（シェルスクリプト経由の書き込みなどは素通りする）。`AGENTS.md` のルールと併用する。
