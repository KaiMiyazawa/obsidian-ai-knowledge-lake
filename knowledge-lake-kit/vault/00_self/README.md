---
icon: 🧭
visibility: private
updated: YYYY-MM-DD
---

# 自分についての一次情報

保管庫を読む AI と人が、**最初に読む場所**です。
「私は誰で、今どこにいて、何を大事にしていて、これまで何があったか」をここに集約します。

他のフォルダが「何をしたか」の記録なのに対して、ここは「私そのもの」の記録です。

## 入口

| ノート | 内容 | 更新頻度 |
| --- | --- | --- |
| [`identity.md`](./identity.md) | 基本属性、所属、公開アカウント | 変化時 |
| [`identity-private.md`](./identity-private.md) | 住所、連絡先、緊急連絡先 | 変化時 |
| [`now.md`](./now.md) | 現在地。今のフェーズと進行中のこと | 月1〜四半期ごと |
| [`timeline.md`](./timeline.md) | 経歴の**原本**となる年表 | 出来事ごと |
| [`values-principles.md`](./values-principles.md) | 判断基準。**AI にどう振る舞ってほしいか**を含む | 考えが変わったとき |
| [`glossary.md`](./glossary.md) | 保管庫の固有名詞辞典。略称・組織名・プロジェクト名 | 用語が増えたとき |
| [`decisions/`](./decisions/README.md) | 意思決定ログ。**なぜそう決めたか**を1決定1ファイルで | 決定ごと |

必要になったら足す候補: `personality.md`（性格診断など恒常的な性質）、`skills.md`（技術スキル・時点付き）、`projects.md`（制作物の索引）。

## 読む順番

1. [`identity.md`](./identity.md) — 前提を揃える
2. [`now.md`](./now.md) — 今のフェーズを誤認しないため。**古い情報で判断しないこと**
3. [`values-principles.md`](./values-principles.md) — 特に「AI への含意」の節
4. 必要に応じて [`timeline.md`](./timeline.md)

知らない固有名詞が出てきたら [`glossary.md`](./glossary.md) を引く。過去の判断の理由は [`decisions/`](./decisions/README.md) を見る。

## 恒常的な性質と、時期依存の心境を混同しない

- **ほぼ変わらないもの**: [`values-principles.md`](./values-principles.md) の「恒常的な判断基準」
- **数ヶ月〜数年で変わるもの**: [`now.md`](./now.md)、[`values-principles.md`](./values-principles.md) の「時期依存の心境」

一時期の落ち込みや、特定の局面での方針を、人生全体の価値観として扱わないこと。

## 記録方針

- 推測で埋めない。分からないことは「未確認」と書く。
- 時点依存の情報には日付を書く。特に [`now.md`](./now.md) は、更新日がないと害になる。
- 機微な情報は [`identity-private.md`](./identity-private.md) に寄せる。

## 取り扱い

- [`identity-private.md`](./identity-private.md) は住所・連絡先を含む。保管庫の外へ出さず、AI に読ませるのはその情報が必要な手続きのときだけ。
- [`decisions/`](./decisions/README.md) と [`values-principles.md`](./values-principles.md) には公開を想定していない記述が含まれる。`89_profile/`・`99_public/` へ書き写さない。
