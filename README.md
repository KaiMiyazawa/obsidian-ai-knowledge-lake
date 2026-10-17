# obsidian-ai-knowledge-lake

Obsidian の保管庫を「AI と共有する自分のナレッジレイク」にして、作業の多くを AI（Claude Code / Codex）に任せられるようにするための一式。
作者が自分の保管庫で実際に運用している仕組みから、個人の中身を抜いて汎用化したもの。

## 中身

| フォルダ | 何か | 最初に読むもの |
| --- | --- | --- |
| [`knowledge-lake-kit/`](knowledge-lake-kit/) | **保管庫の器。** フォルダ構成、AI への指示書（`AGENTS.md`）、各フォルダの README、テンプレート、運用の考え方 | [`START_HERE.md`](knowledge-lake-kit/START_HERE.md)（人間）/ [`SETUP_FOR_AI.md`](knowledge-lake-kit/SETUP_FOR_AI.md)（AI） |
| [`agent-tooling/`](agent-tooling/) | **AI に持たせる道具。** スキル（`/inbox`・`/prioritize` など）、MCP（Gmail 横断・Google Tasks）、Claude Code の mod、フック、CLI、定期実行 | [`README.md`](agent-tooling/README.md)（人間）/ [`FOR_AI.md`](agent-tooling/FOR_AI.md)（AI） |

## 使い方

```bash
git clone https://github.com/KaiMiyazawa/obsidian-ai-knowledge-lake.git
```

1. **保管庫を作る:** [`knowledge-lake-kit/START_HERE.md`](knowledge-lake-kit/START_HERE.md) を上から順に進める。最後は AI がインタビューしながら保管庫を組み立てる。
2. **道具を入れる（任意）:** 保管庫ができて慣れてきたら、保管庫で AI に次のように頼む。
   > `<クローンした場所>/agent-tooling/FOR_AI.md` を読んで、この道具を私の保管庫に入れるのを手伝って

どちらも「AI が読んで、利用者に確認しながら進める」前提で書いてある。全部を一度に入れなくてよい。

## 注意

- 秘密の値（トークン・パスワード・Webhook など）は入っていない。作者の個人情報は伏せ字（`you@gmail.com`、`<MAIN_LIST_ID>` など）にしてある。
- **自分の保管庫は private リポジトリで管理する。** このリポジトリを fork して中身を書き足し、公開したままにしない。
- 道具は作者の環境（macOS、Claude Code・Codex の特定の版）で作ったもの。そのまま動く保証はなく、利用者の環境に合わせて AI と直しながら使う。
- `agent-tooling/outside-vault/gtasks-mcp/` は [alvinjchoi/gtasks-mcp](https://github.com/alvinjchoi/gtasks-mcp)（MIT）を改造したもの。ライセンスは同フォルダの `LICENSE`。
