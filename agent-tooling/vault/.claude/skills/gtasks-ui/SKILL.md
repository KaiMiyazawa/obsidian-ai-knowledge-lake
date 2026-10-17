---
name: gtasks-ui
description: Google Tasks のタスクにスターを付ける・外す、タスクに開始時刻を設定する（カレンダーの時間帯に表示させる）、タスクを繰り返しにする。公式 API（gtasks MCP）に無い操作だけをブラウザで行う自作スキル。「タスクにスター」「タスクを◯時に」「タスクをカレンダーの時間に出して」「毎週◯曜に繰り返し」と言われたら使う。
---

# gtasks-ui — スターと開始時刻だけをブラウザで操作する

Google Tasks API には、スターと時刻の項目がない（`due` は日付だけ）。
**それ以外の操作は必ず gtasks MCP で行う。** このスキルはその2つだけを、
Mac の Chrome（プロフィール `<自分のプロフィール>`）の tasks.google.com で操作する。
経緯と採用理由は [`02_note/mcp-inventory.md`](../../../02_note/mcp-inventory.md) の Google Tasks の節。

## 先に知っておくこと（2026-10-10 に実機で確認）

- **タスクの画面上のIDは `webViewLink` の末尾。** gtasks の `get` / `list` が返す
  `web:https://tasks.google.com/task/<UIID>?sa=6` の `<UIID>` が、DOM の `data-task-id` と一致する。
  API の `id` とは別物。
- **API で `due` を変えると、画面で付けた時刻は消える。** 日付を変えたいときは、
  先に MCP で `due` を更新してから、このスキルで時刻を付ける。
  notes・title など `due` 以外の更新では、スターも時刻も消えない。
- **タブが裏にあると描画されない。** `scale: 0.1` のスクリーンショットを1枚撮ると描画されるうえ、
  座標の基準になる幅（`coordinate frame: <W>x<H>`）も分かる。スクリーンショットはこの用途だけにして、
  確認は JS で文字を読む。
- **JS の `.click()` やイベントの送出は、スターと日付チップには効かない。** これらは
  座標を JS で求めてから、`computer` の `left_click` で実際にクリックする。
  ただし時刻ダイアログの「完了」ボタンは JS の `.click()` で効く。
- **ボタンは aria-label の前方一致で探す。** `/スター/` のような部分一致にすると、
  タイトルに同じ語を含む「完了とする: …」ボタンに当たって、タスクを完了にしてしまう（実際に起きた）。
- 予定（カレンダーのイベント）にはスター機能自体がない。対象はタスクだけ。
- **スターの状態はホバーしなくても読める**（2026-10-16）。全リストの行の `[スター付き]` ボタンの aria-label（`から削除`＝スター済み）を JS で一括で読めば、今どれにスターが付いているかが1回で分かる。付け外しのクリックだけはホバーが要る。

## 手順

### 0. 準備
1. gtasks MCP の `get`（または `search`）で対象タスクを特定し、`web:` から `<UIID>` を取る。
   時刻を付けるのに期限がまだない場合は、ここで `update` を使って `due` を入れておく。
2. `tabs_context_mcp` → `tabs_create_mcp` → `navigate` で `https://tasks.google.com/tasks/` を開く。
3. `computer` の `screenshot`（`scale: 0.1`）を撮り、`coordinate frame` の幅 `W` を控える。

以下の JS では `UIID` と `W` を実際の値に置き換える。

### 1. 行を表示し、座標を得る
```js
let row; for (let i=0;i<30&&!(row=document.querySelector('[data-task-id="UIID"][aria-label]'));i++) await new Promise(r=>setTimeout(r,500));
row.scrollIntoView({block:'center'});
const k=W/innerWidth, c=e=>{const r=e.getBoundingClientRect();return [Math.round((r.x+r.width/2)*k),Math.round((r.y+r.height/2)*k)]};
const chip=row.querySelector('[role=button][aria-label$="にスケジュール設定されています"]');
JSON.stringify({label:row.getAttribute('aria-label'), row:c(row), chip:chip&&c(chip)})
```
`label` で対象タスクかどうかを確かめる（タイトル・日付・時刻が文で入っている）。
**行の座標が画面の高さを超えるときは、`scrollIntoView` もリストの `scrollTop` 変更も効かないことがある**（2026-10-14）。
その場合は `computer` の `scroll` でリストの列の上をホイールでスクロールしてから、座標を取り直す。

### 2a. スターを付ける・外す
1. `computer` の `hover` で `row` の座標に合わせる（スターのボタンはホバー中しか表示されない）。
2. JS で、スターのボタンの座標と現在の状態を得る。
   ```js
   const row=document.querySelector('[data-task-id="UIID"][aria-label]'), k=W/innerWidth;
   const b=[...row.querySelectorAll('button')].find(b=>(b.getAttribute('aria-label')||'').startsWith('[スター付き]'));
   const r=b.getBoundingClientRect(); JSON.stringify([Math.round((r.x+r.width/2)*k),Math.round((r.y+r.height/2)*k),b.getAttribute('aria-label')])
   ```
   ラベルが `[スター付き] に追加` なら未スター、`[スター付き] から削除` ならスター済み。
   目的の状態になっていれば、何もしない。
   **座標が `[0,0]` になることがある**（2026-10-14。ホバー後もボタンの大きさが0のまま）。その場合は
   行にホバーした状態で `scale: 0.5` のスクリーンショットを撮り、行の右端に出る星の位置をクリックする。
3. その座標を `left_click` する。
4. もう一度 2 の JS を実行し、ラベルが逆になったことを確認する。
   **クリック後もラベルが古いままのことがある**（2026-10-14、実際にはスターは付いていた）。その場合は
   行の右端を `zoom` で見て、星が青く塗られているかで判断する。もう一度クリックすると外れてしまう。

### 2b. 開始時刻を設定する
1. 手順1で得た `chip` の座標を `left_click` する（日付ピッカーが開く）。
   **ピッカーが開かず、タスクが展開されるだけのことがある**（2026-10-10、繰り返しタスクで発生）。
   その場合は展開でチップの位置が動いているので、手順1の JS で `chip` の座標を取り直して、もう一度クリックする。
   繰り返しタスクでも、ピッカーにはその回の日付と時刻欄だけが出る。
   **繰り返しタスクで時刻を付けても、変わるのはその回だけ。** 次の回以降は元のまま（2026-10-10 に本人が確認）。
2. JS で時刻欄にフォーカスする。`no input` なら、0.5 秒ほど待ってからやり直す。
   ```js
   await new Promise(r=>setTimeout(r,500)); const i=document.querySelector('input[aria-label="開始時刻を設定"]'); i?(i.focus(),i.select(),'ok'):'no input'
   ```
3. `computer` の `type` で `HH:MM`（例 `9:15`）を入力し、`key` で `Enter` を押す。**Enter だけでは保存されない。**
4. JS で「完了」を押してから確認する。
   ```js
   [...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='完了'&&b.offsetParent).click();
   await new Promise(r=>setTimeout(r,1500));
   document.querySelector('[data-task-id="UIID"][aria-label]').getAttribute('aria-label')
   ```
   `日付が 明日、9:15` のように時刻が入っていれば成功。古い表示のままなら、0.1 のスクリーンショットを
   1枚撮って描画させてから、最後の行だけを再実行する。
5. 時刻付きのタスクは、Google カレンダーの時間帯に表示される。

### 2c. 繰り返しを設定する（2026-10-13 に確認）
API に繰り返しの項目はない。先に MCP で `due` を初回の日付にしておく。
1. 手順1の `chip` を `left_click` → ピッカーの「繰り返し」をクリック。
2. 「1 日ごと ▼」のプルダウンをクリックして「週間ごと」を選ぶ。曜日ボタン（日〜土）が出て、`due` の曜日が最初から選択されている。
   追加したい曜日を `left_click` する（青くなれば選択。zoom で確認）。
3. 「完了」をクリック。行に「繰り返し」のアイコンが付けば成功。API 上の `id` は変わらない。

### 3. 後片付け
作ったタブを `tabs_close_mcp` で閉じる。

## 止める条件
- `data-task-id` の行・スターのボタン・`開始時刻を設定` の欄が見つからない
  → Google 側の画面が変わった可能性。2回試してだめなら止めて報告し、このスキルの手順を直す。
- 複数のタスクを一括で操作するときは、最初の1件で結果を確認してから続ける。
- 時刻を外す（終日に戻す）操作は、まだ確認していない。必要になったら、テスト用のタスクで確かめてから手順を追記する。
