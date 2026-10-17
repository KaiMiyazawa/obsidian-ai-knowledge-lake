# claude-mods

Claude Code の自作 mod（function hooks のプラグイン）。この保管庫の運用ルールに合わせたもの。
各 mod の内容・判断の経緯は [`../../02_note/claude-code-mods.md`](../../02_note/claude-code-mods.md) が原本。

このフォルダをローカルのマーケットプレイス `obsidian-vault-mods` として登録している。

```bash
claude plugin marketplace add ~/Desktop/Obsidian/tools/claude-mods
claude plugin install <mod>@obsidian-vault-mods
```

編集したら、開いているセッションで `/reload-plugins` を実行すると、このフォルダから読み直される。
変更前に `claude plugin validate <mod>` と `claude plugin test <mod>` を通す。
