// 巡回（案B/C）。指定したチャンネルを順に開き、最古の投稿までゆっくり上へスクロールする。
// 記録そのものは hook.js（受け身の記録）が行う。ここは画面を動かすだけで、自分からは API を呼ばない。
// 操作はポップアップ（popup.html）から。進捗・再開位置は chrome.storage.local の "crawl" に保存する。
(() => {
  const TAG = "discord-passive-recorder";
  const DEFAULTS = {
    minDelaySec: 5, maxDelaySec: 12,        // 1回スクロールするごとの待ち
    channelPauseMinSec: 30, channelPauseMaxSec: 90, // チャンネルを切り替える前の休憩
    noChannelRest: false,                  // チャンネル間の通常の休憩だけ省略する
    breakEvery: 50, breakMinSec: 120, breakMaxSec: 300, // 読み込み N 回ごとの長い休憩
    restEveryLoads: 300,                    // 読み込み N 回ごとに、さらに長く休む（一晩放置する前提）
    restMinMin: 30, restMaxMin: 60,         // その休憩（分）
    rateLimitRestMin: 30,                   // メッセージ読み込みで 429 が返ったときの最低休憩（分）
    maxRateLimits: 3,                       // 同じ実行の中で 429 がこの回数に達したら完全に止める
    stallPasses: 2,                         // 途中で進まなくなったチャンネルを、最後に何周まで再挑戦するか
    skipCompleted: true,                    // 受信サーバーに「最古まで取り終えた」記録があるチャンネルは飛ばす
    noScrollRest: false,                    // チャンネル内ではスクロールの間に休まない（休憩はチャンネルの切れ目で取る）
    fastWaitMaxSec: 10,                     // そのモードで、次の読み込みを待つ上限（これを超えたら「進まない」扱い）
    stallLimit: 6,                          // 最古の投稿が変わらないまま何回続いたら諦めるか
  };

  let running = false;
  let stopReason = null;
  let loads = 0;
  let restAt = 0; // 最後に長い休憩を取った時点の loads
  let restUntil = 0;     // 一時的な休憩（429・読み込み上限）の終わり。止めずにここまで待ってから続ける
  let settings = { ...DEFAULTS };
  const INSTANCE = Math.random().toString(36).slice(2); // 複数の Discord タブで二重に動かないための識別子

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const rand = (a, b) => (a + Math.random() * (b - a)) * 1000;
  const getState = async () => (await chrome.storage.local.get("crawl")).crawl || { done: {}, resume: {}, log: [] };
  const setState = (s) => chrome.storage.local.set({ crawl: s });
  const patch = async (fn) => { const s = await getState(); fn(s); await setState(s); return s; };
  const log = (text) => patch((s) => {
    s.log = [...(s.log || []), `${new Date().toLocaleTimeString("ja-JP")} ${text}`].slice(-40);
  });

  // hook.js からの通知: API 応答の件数を数え、429 なら即停止
  window.addEventListener("message", (e) => {
    const p = e.source === window && e.data && e.data.__dpr === TAG ? e.data.payload : null;
    if (!p || !running) return;
    if (p.kind === "messages" && p.source === "api") loads++;
    if (p.kind === "ratelimit") {
      // メッセージの読み込み、または Discord 全体（global）の制限なら即停止。
      // それ以外（在席通知 /users/@me/meaningfully-online など、タブの切り替えで Discord 自身が連打するもの）は
      // 巡回の速さとは無関係なので、記録して少し休むだけにする（2026-09-29 に後者で止まった）
      if (p.global || /\/messages/.test(p.url)) {
        patch((s) => { s.rateHits = (s.rateHits || 0) + 1; }).then((s) => {
          if (s.rateHits >= settings.maxRateLimits) {
            stopReason = `Discord から 429（速すぎる）が ${s.rateHits} 回返ったので完全に停止: ${p.url}`;
            return;
          }
          const min = Math.max(settings.rateLimitRestMin, ((p.retryAfter || 0) * 10) / 60);
          restUntil = Math.max(restUntil, Date.now() + min * 60000);
          log(`429（${p.url}${p.global ? "、全体の制限" : ""}）。${Math.round(min)} 分休んでから続ける（${s.rateHits}/${settings.maxRateLimits} 回目）`);
        });
      } else {
        restUntil = Math.max(restUntil, Date.now() + Math.max(60, (p.retryAfter || 0) * 2) * 1000);
        log(`巡回と無関係な通信で 429（${p.url}）。止めずに少し休む`);
      }
    }
  });

  // --- 画面操作 ---
  const navigate = (path) => {
    history.pushState({}, "", path);
    dispatchEvent(new PopStateEvent("popstate", { state: {} }));
  };

  const scrollerOf = (el) => {
    for (let n = el; n; n = n.parentElement) {
      if (n.scrollHeight > n.clientHeight + 5 && /auto|scroll/.test(getComputedStyle(n).overflowY)) return n;
    }
    return null;
  };

  const waitFor = async (fn, timeoutMs) => {
    const end = Date.now() + timeoutMs;
    while (Date.now() < end) {
      const v = fn();
      if (v) return v;
      await sleep(500);
    }
    return null;
  };

  const waitVisible = async () => {
    let warned = false;
    while (document.hidden && !stopReason) {
      if (!warned) { warned = true; await log("タブが裏に回ったので一時停止中（Discord のタブを前面に出すと再開）"); }
      await sleep(2000);
    }
  };

  const pause = async (ms) => {
    const end = Date.now() + ms;
    while (Date.now() < end && !stopReason) await sleep(Math.min(1000, end - Date.now()));
  };

  // 閉じているもの（サーバーのフォルダ、チャンネルのカテゴリ）を一時的に開いて中を読み、読み終えたら閉じ直す。
  // 開閉状態は Discord の設定として保存されるので、必ず元に戻す。
  const toggleByListId = async (listId) => {
    const el = document.querySelector(`[data-list-item-id="${listId}"]`);
    if (el) { el.click(); await sleep(500 + Math.random() * 300); }
    return Boolean(el);
  };

  // 左端のサーバー一覧から、参加している全サーバーの ID と名前を集める（閉じたフォルダの中も含む）
  const listGuilds = async () => {
    const opened = [];
    for (const f of document.querySelectorAll('[data-list-item-id^="guildsnav___"][aria-expanded="false"]')) {
      const id = f.getAttribute("data-list-item-id");
      if (await toggleByListId(id)) opened.push(id);
    }
    await sleep(800);
    const guilds = new Map();
    for (const e of document.querySelectorAll('[data-list-item-id^="guildsnav___"]:not([aria-expanded])')) {
      const id = e.getAttribute("data-list-item-id").slice("guildsnav___".length);
      const holder = e.closest("[data-dnd-name]");
      if (/^\d+$/.test(id) && holder) guilds.set(id, holder.getAttribute("data-dnd-name"));
    }
    for (const id of opened) {
      const el = document.querySelector(`[data-list-item-id="${id}"]`);
      if (el && el.getAttribute("aria-expanded") === "true") await toggleByListId(id);
    }
    return [...guilds].map(([id, name]) => ({ id, name }));
  };

  // サーバーの左サイドバーを上から下までスクロールして、チャンネルへのリンクを集める。
  // 閉じたカテゴリは、スクロールしながら開いて中を拾い、最後に閉じ直す。
  const isForumLabel = (label) => /[（(]\s*(?:フォーラムチャンネル|forum channel)\s*[）)]\s*$/i.test(label);

  const harvestGuild = async (guildId) => {
    if (!location.pathname.startsWith(`/channels/${guildId}`)) navigate(`/channels/${guildId}`);
    const first = await waitFor(() => document.querySelector(`a[href^="/channels/${guildId}/"]`), 15000);
    if (!first) return [];
    const found = new Map();
    const grab = () => document.querySelectorAll(`a[href^="/channels/${guildId}/"]`).forEach((a) => {
      const id = a.getAttribute("href").split("/")[3];
      if (/^\d+$/.test(id) && !found.has(id)) {
        const label = (a.getAttribute("aria-label") || a.innerText || "").trim();
        found.set(id, { label, forum: isForumLabel(label) });
      }
    });
    const sc = scrollerOf(first);
    const opened = [];
    const openCollapsed = async () => {
      for (const c of sc.querySelectorAll('[aria-expanded="false"]')) {
        const holder = c.closest('[data-list-item-id^="channels___"]') || (c.matches('[data-list-item-id^="channels___"]') ? c : null);
        const id = holder && holder.getAttribute("data-list-item-id");
        if (!id || opened.includes(id)) continue;
        c.click();
        opened.push(id);
        await sleep(500 + Math.random() * 300);
      }
    };
    const sweep = async (fn) => {
      sc.scrollTop = 0;
      await sleep(600);
      for (let i = 0; i < 200; i++) {
        await fn();
        if (sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 2) break;
        sc.scrollTop += sc.clientHeight * 0.7;
        await sleep(400);
      }
    };
    if (sc) {
      await sweep(async () => { await openCollapsed(); grab(); });
      if (opened.length) {
        // 閉じ直す（仮想リストなので、もう一度スクロールしながら見えたものから閉じる）
        const toClose = new Set(opened);
        await sweep(async () => {
          for (const id of [...toClose]) {
            const el = document.querySelector(`[data-list-item-id="${id}"]`);
            const toggle = el && (el.matches("[aria-expanded]") ? el : el.querySelector("[aria-expanded]"));
            if (toggle && toggle.getAttribute("aria-expanded") === "true") { toggle.click(); toClose.delete(id); await sleep(400); }
            else if (toggle) toClose.delete(id);
          }
        });
      }
      sc.scrollTop = 0;
    }
    grab();
    await log(`サーバー ${guildId}: チャンネル ${found.size} 件を検出` + (opened.length ? `（閉じたカテゴリ ${opened.length} 件を一時的に開いて読んだ）` : ""));
    return [...found].map(([channelId, info]) => ({ guildId, channelId, ...info }));
  };

  // URL だけは先に切り替わる。前のチャンネルや右側のスレッドの一覧を拾わないよう、投稿の ID も照合する。
  const messageListFor = (channelId = location.pathname.split("/")[3]) =>
    [...document.querySelectorAll('ol[data-list-id="chat-messages"]')].find((list) =>
      list.querySelector(`li[id^="chat-messages-${channelId}-"]`)) || null;

  const oldestId = (ol) => {
    const li = ol.querySelector('li[id^="chat-messages-"]');
    return li ? li.id.split("-").pop() : null;
  };

  const currentScroller = () => {
    const list = messageListFor();
    return list && scrollerOf(list);
  };

  const wheelUp = (sc, dy) => sc.dispatchEvent(new WheelEvent("wheel", { deltaY: -dy, bubbles: true, cancelable: true }));

  // 人のスクロールに近づける: 画面の6割ずつ、ホイール入力と一緒に上げていき、上端でもう数回ホイールを送る。
  // shake=true のときは、先に画面1枚半ほど下げてから上がる（上端に張り付いたままの状態を崩す）。
  const scrollUp = async (shake) => {
    let sc = currentScroller();
    if (!sc) return;
    if (shake) {
      sc.scrollTop = Math.min(sc.scrollHeight - sc.clientHeight, sc.scrollTop + sc.clientHeight * 1.5);
      await sleep(1500);
      sc = currentScroller() || sc;
    }
    for (let i = 0; i < 60 && sc.scrollTop > 0 && !stopReason; i++) {
      const dy = Math.min(sc.scrollTop, sc.clientHeight * 0.6);
      sc.scrollTop -= dy;
      wheelUp(sc, dy);
      await sleep(150 + Math.random() * 200);
    }
    for (let i = 0; i < 3; i++) { wheelUp(sc, 300); await sleep(200 + Math.random() * 200); }
  };

  // いま読み込まれている一番古い投稿へのリンクを開き直し、Discord の表示状態を作り直す
  const resetView = async (guildId, channelId) => {
    const list = messageListFor(channelId);
    const oldest = list && oldestId(list);
    await log(`#${channelId}: 表示を作り直して再挑戦`);
    navigate(`/channels/${guildId}`);
    await sleep(2500);
    navigate(`/channels/${guildId}/${channelId}` + (oldest ? `/${oldest}` : ""));
    await waitFor(() => messageListFor(channelId), 15000);
    await sleep(2000);
    await scrollUp(false);
  };

  // 止まったときの状態（次の原因調査用）
  const diagnose = () => {
    const sc = currentScroller();
    const list = messageListFor();
    const top = list && list.children[1];
    return ` [st=${sc ? Math.round(sc.scrollTop) : "-"} sh=${sc ? sc.scrollHeight : "-"} ch=${sc ? sc.clientHeight : "-"}` +
      ` 件数=${list ? list.querySelectorAll('li[id^="chat-messages-"]').length : "-"}` +
      ` 先頭=${top ? String(top.className).split(" ")[0] || top.tagName : "-"}` +
      ` 表示=${document.visibilityState} フォーカス=${document.hasFocus()}]`;
  };

  // 1チャンネルを最古まで遡る。戻り値: "top" | "skipped"（フォーラム・メッセージ欄が無い） | "stalled"（途中で進まない） | "stopped"
  const crawlChannel = async ({ guildId, channelId, label, forum }, settings) => {
    if (forum) {
      await log(`${label || "#" + channelId}: フォーラムなので飛ばす（投稿一覧・スレッドは巡回対象外）`);
      return "skipped";
    }
    const state = await getState();
    // 前回の巡回の位置がなければ、受信サーバーに記録済みの一番古い投稿へ飛んでから遡る（持っている分を読み直さない）
    // 巡回の前回位置と記録済みの最古のうち、古い（ID が小さい）ほうから始める
    const candidates = [state.resume[channelId], knownOldest[channelId]].filter(Boolean);
    const resume = candidates.length ? candidates.reduce((a, b) => (BigInt(a) < BigInt(b) ? a : b)) : null;
    navigate(`/channels/${guildId}/${channelId}` + (resume ? `/${resume}` : ""));
    const ol = await waitFor(() => stopReason || (location.pathname.split("/")[3] === channelId &&
      messageListFor(channelId)), 15000);
    if (stopReason) return "stopped";
    if (!ol) { await log(`#${channelId}: メッセージ欄が無い（フォーラム・ボイス・権限なし）ので飛ばす`); return "skipped"; }
    await sleep(2000);
    await log(`${document.title.replace(/^\(\d+\)\s*/, "")} を遡り中` + (resume ? "（記録済みの一番古い位置から）" : ""));

    let prev = null;
    let stall = 0;
    let lastBreakAt = loads;
    while (!stopReason) {
      await waitVisible();
      if (Date.now() < restUntil) await pause(restUntil - Date.now());
      if (stopReason) break;
      // 先頭に「#〇〇へようこそ！」（id = chat-messages-<channel>-<channel>）が出たら最古に到達
      if (document.getElementById(`chat-messages-${channelId}-${channelId}`)) return "top";
      if (!settings.noScrollRest && await longRestIfDue()) continue;
      // 進まないときは段階的に手を変える（2026-09-29: Discord が表示件数を減らした直後に、
      // スクロール位置の変化だけでは次を読み込まなくなる現象を確認。ホイール入力で抜けられることがある）
      if (stall >= 3 && stall % 2 === 1) await resetView(guildId, channelId);
      else await scrollUp(stall >= 2);
      if (settings.noScrollRest) {
        // 休まないモード: 一番古い投稿が変わる（＝次が読み込まれる）まで待ったら、すぐ次へ
        await waitFor(() => {
          const l = messageListFor(channelId);
          const id = l && oldestId(l);
          return stopReason || (id && id !== prev) ||
            document.getElementById(`chat-messages-${channelId}-${channelId}`);
        }, settings.fastWaitMaxSec * 1000);
        await sleep(300 + Math.random() * 400); // 描画が落ち着くのを待つだけ
      } else {
        await pause(rand(settings.minDelaySec, settings.maxDelaySec));
      }

      // 判定は待った後に取り直した要素で行う（Discord が一覧を作り直すと、前の要素は古いまま残るため）
      const list = messageListFor(channelId);
      const now = list && oldestId(list);
      if (now && now !== prev) {
        stall = 0;
        prev = now;
        await patch((s) => { s.resume[channelId] = now; s.loads = loads; });
      } else {
        stall++;
        await log(`#${channelId}: 進まない（${stall}/${settings.stallLimit}）${diagnose()}`);
        if (stall >= settings.stallLimit) {
          await log(`#${channelId}: 中断（次回の実行で、この位置から再挑戦する）`);
          return "stalled";
        }
      }
      if (!settings.noScrollRest && loads - lastBreakAt >= settings.breakEvery) {
        lastBreakAt = loads;
        const ms = rand(settings.breakMinSec, settings.breakMaxSec);
        await log(`長めの休憩 ${Math.round(ms / 1000)} 秒`);
        await pause(ms);
      }
    }
    return "stopped";
  };

  // 入力: 1行に1サーバー。サーバーまたはその中のチャンネルの URL（どちらもサーバー全体として扱う）、
  // またはサーバー ID だけ。DM（@me）はサーバーではないので対象外。
  const parseTargets = (text) => [...new Set(text.split(/\s+/).map((line) => {
    const m = /discord\.com\/channels\/(\d+)/.exec(line) || /^(\d{15,25})$/.exec(line.trim());
    return m ? m[1] : null;
  }).filter(Boolean))];

  // 「最古まで取り終えた」チャンネルの一覧を受信サーバーから読む（読めなければ null）。
  // あわせて、この機能より前に巡回で完了していたチャンネル（進捗の記録にだけあるもの）を受信サーバーへ書き写す。
  let knownOldest = {}; // channelId → 受信サーバーに記録済みの一番古いメッセージ ID

  const loadCompleted = async () => {
    const state = await getState();
    const tops = Object.entries(state.done || {}).filter(([, d]) => d.result === "top").map(([id]) => id);
    let res;
    try { res = await chrome.runtime.sendMessage({ type: "get-completed" }); } catch { res = null; }
    if (!res || !res.ok) return null;
    const set = new Set(res.channels);
    knownOldest = res.oldest || {};
    for (const id of tops) {
      if (set.has(id)) continue;
      window.postMessage({ __dpr: TAG, payload: { kind: "complete", channel_id: id, via: "crawl-progress", context: {} } }, location.origin);
      set.add(id);
    }
    return set;
  };

  // 読み込み restEveryLoads 回ごとの長い休憩。取ったら true
  const longRestIfDue = async () => {
    if (loads - restAt < settings.restEveryLoads) return false;
    restAt = loads;
    const ms = rand(settings.restMinMin * 60, settings.restMaxMin * 60);
    await log(`読み込み ${settings.restEveryLoads} 回ごとの長い休憩 ${Math.round(ms / 60000)} 分`);
    await pause(ms);
    return true;
  };

  const channelPause = async () => {
    const ms = rand(settings.channelPauseMinSec, settings.channelPauseMaxSec);
    await log(`次のチャンネルまで ${Math.round(ms / 1000)} 秒休憩`);
    await pause(ms);
  };

  // resumed=true はページの再読み込み後の自動再開（429 の回数などを引き継ぐ）
  const run = async (text, userSettings, resumed = false) => {
    settings = { ...DEFAULTS, ...userSettings };
    running = true;
    stopReason = null;
    loads = 0;
    restAt = 0;
    restUntil = 0;
    await patch((s) => {
      Object.assign(s, { running: true, input: text, settings, loads: 0, stopRequested: false, heartbeat: { id: INSTANCE, at: Date.now() } });
      if (!resumed) { s.startedAt = new Date().toISOString(); s.rateHits = 0; }
    });
    const beat = setInterval(() => patch((s) => { s.heartbeat = { id: INSTANCE, at: Date.now() }; s.loads = loads; }), 30000);
    await log(resumed ? "ページの再読み込み後、自動で再開" : "開始");
    try {
      const queue = [];
      const guilds = parseTargets(text);
      if (!guilds.length) stopReason = "対象のサーバーが見つからない（サーバーの URL か ID を入れる）";
      for (const guildId of guilds) {
        if (stopReason) break;
        const channels = await harvestGuild(guildId);
        queue.push(...channels);
        // ポップアップでサーバーごとの進み具合を出すため、サーバー → チャンネルの対応を残す
        await patch((s) => { s.guildChannels = { ...(s.guildChannels || {}), [guildId]: channels.map((c) => c.channelId) }; });
      }
      const seen = new Set();
      let todo = queue.filter((t) => !seen.has(t.channelId) && seen.add(t.channelId));
      // 記録済みの位置は常に読む（遡りの起点に使う）。取得済みを飛ばすかはチェック次第
      const completed = stopReason ? null : await loadCompleted();
      if (!completed && !settings.skipCompleted) await log("受信サーバーにつながらないので、記録済みの位置は使わず最新から遡る");
      if (settings.skipCompleted && !stopReason) {
        if (!completed) {
          stopReason = "受信サーバーにつながらず取得済みのチャンネルを確認できないので停止（receiver.py を起動するか、「取得済みは飛ばす」を外す）";
        } else {
          const before = todo.length;
          todo = todo.filter((t) => !completed.has(t.channelId));
          await log(`取得済み ${before - todo.length} チャンネルを飛ばす（残り ${todo.length}）`);
        }
      }
      await patch((s) => { s.total = todo.length; });
      let first = true;
      // 1周目で途中から進まなくなったチャンネルは、最後にまとめて再挑戦する（最大 stallPasses 周）
      for (let pass = 0; pass <= settings.stallPasses && !stopReason; pass++) {
        const remaining = [];
        for (const t of todo) if (!(await getState()).done[t.channelId]) remaining.push(t);
        if (!remaining.length) break;
        if (pass > 0) await log(`進まなかった ${remaining.length} チャンネルに再挑戦（${pass}/${settings.stallPasses} 周目）`);
        for (const target of remaining) {
          if (stopReason) break;
          if (!target.forum && !first && !settings.noChannelRest) await channelPause();
          // 休まないモードでは、長い休憩もチャンネルの切れ目で取る
          if (settings.noScrollRest) await longRestIfDue();
          if (stopReason) break;
          if (!target.forum) first = false;
          const result = await crawlChannel(target, settings);
          if (result === "stalled" || result === "stopped") continue; // 完了扱いにしない
          await patch((s) => { s.done[target.channelId] = { result, at: new Date().toISOString() }; });
          await log(`#${target.channelId}: ${result === "top" ? "最古まで到達" : "飛ばした"}`);
        }
      }
      if (!stopReason) {
        const state = await getState();
        const notDone = todo.filter((t) => !state.done[t.channelId]).length;
        stopReason = notDone ? `終了（${notDone} チャンネルは途中で進まなかった。次回「開始」でその位置から再挑戦）` : "すべて完了";
      }
    } catch (e) {
      stopReason = `エラーで停止: ${e && e.message}`;
    }
    clearInterval(beat);
    running = false;
    await patch((s) => { s.running = false; s.loads = loads; s.heartbeat = null; });
    await log(stopReason);
  };

  const aliveElsewhere = (s) => s.running && s.heartbeat && s.heartbeat.id !== INSTANCE && Date.now() - s.heartbeat.at < 90000;

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === "list-guilds") {
      if (running) { sendResponse({ ok: false, error: "巡回中は一覧を取り直せない" }); return; }
      listGuilds().then((guilds) => sendResponse({ ok: true, guilds })).catch((e) => sendResponse({ ok: false, error: String(e) }));
      return true;
    }
    if (msg.type === "crawl-start") {
      getState().then((s) => {
        if (running || aliveElsewhere(s)) { sendResponse({ ok: false, error: "すでに実行中（別の Discord タブの場合も含む）" }); return; }
        run(msg.text, msg.settings || {});
        sendResponse({ ok: true });
      });
      return true; // 非同期で応答する
    }
  });

  // 停止はポップアップが storage に stopRequested を立てる（どのタブで動いていても止まる）
  chrome.storage.onChanged.addListener((changes) => {
    const s = changes.crawl && changes.crawl.newValue;
    if (s && s.stopRequested && running && !stopReason) stopReason = "手動で停止";
  });

  // ページが読み直された（Discord の自動更新など）ときは、前の実行を自動で引き継ぐ。
  // 別のタブがまだ動いている（30 秒ごとの生存記録が新しい）なら引き継がない。
  // 読み直した直後は、読み直す前の自分の生存記録がまだ新しいので、古くなる（90 秒）まで待ってから判断する。
  (async () => {
    if (!(await getState()).running) return;
    for (let i = 0; i < 12; i++) {
      await sleep(15000 + Math.random() * 5000);
      const again = await getState();
      if (!again.running || running) return;
      if (!aliveElsewhere(again)) break;
      if (i === 11) return; // 別のタブが動き続けている
    }
    await patch((x) => { x.heartbeat = { id: INSTANCE, at: Date.now() }; });
    await sleep(2000);
    const mine = await getState();
    if (mine.heartbeat && mine.heartbeat.id === INSTANCE) run(mine.input || "", mine.settings || {}, true);
  })();
})();
