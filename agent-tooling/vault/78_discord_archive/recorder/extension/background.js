// 受け取った記録を chrome.storage.local に溜め、ローカルの受信サーバーへ送る。
// サーバーが止まっていても失わない（起動したら alarms で再送する）。
const ENDPOINT = "http://127.0.0.1:8765/ingest";
const MAX_QUEUE = 50000;
const BATCH = 200;

let chain = Promise.resolve();
const withLock = (fn) => (chain = chain.then(fn, fn));

const getQueue = async () => (await chrome.storage.local.get("queue")).queue || [];
const setQueue = (queue) => chrome.storage.local.set({ queue });

const enqueue = (item) => withLock(async () => {
  const queue = await getQueue();
  queue.push(item);
  if (queue.length > MAX_QUEUE) queue.splice(0, queue.length - MAX_QUEUE);
  await setQueue(queue);
});

const flush = () => withLock(async () => {
  let queue = await getQueue();
  while (queue.length) {
    const items = queue.slice(0, BATCH);
    let res;
    try {
      res = await fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Discord-Recorder": "1" },
        body: JSON.stringify({ items }),
      });
    } catch {
      break; // サーバー停止中。次の alarm で再送
    }
    if (!res.ok) break;
    queue = queue.slice(items.length);
    await setQueue(queue);
  }
  await chrome.action?.setBadgeText?.({ text: queue.length ? String(queue.length) : "" });
});

// 巡回（content script）はページの制約で 127.0.0.1 に直接つなげないので、ここで代わりに取る
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "get-completed") {
    fetch(ENDPOINT.replace("/ingest", "/completed"), { headers: { "X-Discord-Recorder": "1" } })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((body) => sendResponse({ ok: true, channels: body.channels || [], oldest: body.oldest || {} }))
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "record") enqueue({ ...msg.payload, captured_at: msg.captured_at }).then(flush);
});

chrome.alarms.create("flush", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "flush") flush(); });
