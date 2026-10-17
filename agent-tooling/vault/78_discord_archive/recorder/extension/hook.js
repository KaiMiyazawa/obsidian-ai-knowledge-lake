// ページ側（MAIN world）で動く。Discord 自身が受け取った応答と、画面に描画されたメッセージを写し取るだけ。
// 自分からは一切リクエストを送らない。リクエストヘッダー（Authorization トークン）には触れない。
(() => {
  const TAG = "discord-passive-recorder";
  const TARGET = /\/api\/v\d+\/(channels|guilds)\/[^?]*\/(messages|threads)/;

  const post = (payload) => window.postMessage({ __dpr: TAG, payload }, window.location.origin);
  const context = () => ({ path: location.pathname, title: document.title });

  // --- API 応答から Discord のメッセージオブジェクトを探す ---
  const isMessage = (o) =>
    o && typeof o === "object" && typeof o.id === "string" && typeof o.channel_id === "string" &&
    o.author && typeof o.author === "object" && typeof o.timestamp === "string";

  const collect = (node, out, depth = 0) => {
    if (!node || typeof node !== "object" || depth > 6) return;
    if (isMessage(node)) out.push(node);
    for (const v of Array.isArray(node) ? node : Object.values(node)) collect(v, out, depth + 1);
  };

  const apiSeen = new Set();
  const handleBody = (url, body) => {
    const messages = [];
    collect(body, messages);
    if (!messages.length) return;
    for (const m of messages) apiSeen.add(m.id);
    post({ kind: "messages", source: "api", url: String(url).split("?")[0], context: context(), messages });
  };

  const parseText = (text) => { try { return JSON.parse(text); } catch { return null; } };

  // 429 の中身: global=true なら Discord 全体の制限、retry_after は待つべき秒数
  const postRateLimit = (url, body, globalHeader) => post({
    kind: "ratelimit",
    url: String(url).split("?")[0],
    global: Boolean((body && body.global) || globalHeader === "true"),
    retryAfter: body && typeof body.retry_after === "number" ? body.retry_after : null,
  });

  // XHR（Discord のクライアントは現状こちらを使う。2026-09-29 確認）
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__dprTarget = String(method).toUpperCase() === "GET" && TARGET.test(String(url)) ? String(url) : null;
    this.__dprApi = /\/api\/v\d+\//.test(String(url));
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    // Discord から「速すぎる」(429) が返ったら、巡回（crawler.js）が即停止できるよう知らせる
    if (this.__dprApi) {
      this.addEventListener("load", () => {
        if (this.status !== 429) return;
        let body = null;
        try { body = this.responseType === "json" ? this.response : parseText(this.responseText); } catch { /* 無視 */ }
        postRateLimit(this.responseURL, body, this.getResponseHeader("x-ratelimit-global"));
      });
    }
    if (this.__dprTarget) {
      this.addEventListener("load", () => {
        try {
          if (this.status < 200 || this.status >= 300) return;
          const body = this.responseType === "json" ? this.response
            : (this.responseType === "" || this.responseType === "text") ? parseText(this.responseText) : null;
          if (body) handleBody(this.__dprTarget, body);
        } catch { /* 記録の失敗で Discord の動作を妨げない */ }
      });
    }
    return origSend.apply(this, arguments);
  };

  // fetch（将来クライアントが切り替わったときの保険）
  const origFetch = window.fetch;
  window.fetch = function (input, init) {
    const p = origFetch.apply(this, arguments);
    try {
      const url = typeof input === "string" ? input : input && input.url;
      const method = (init && init.method) || (input && input.method) || "GET";
      if (url && /\/api\/v\d+\//.test(url)) {
        p.then((res) => res.status === 429 && res.clone().json().catch(() => null)
          .then((b) => postRateLimit(url, b, res.headers.get("x-ratelimit-global")))).catch(() => {});
      }
      if (url && method.toUpperCase() === "GET" && TARGET.test(url)) {
        p.then((res) => res.ok && res.clone().json().then((b) => handleBody(url, b)).catch(() => {})).catch(() => {});
      }
    } catch { /* 同上 */ }
    return p;
  };

  // --- 画面の描画から拾う（リアルタイムに届いたメッセージの補完。API で取れた分は送らない） ---
  const domSeen = new Set();
  const pending = new Set();
  const ID_RE = /^chat-messages-(\d+)-(\d+)$/;
  const MEDIA_RE = /(cdn\.discordapp\.com|media\.discordapp\.net)\//;

  const authorOf = (li) => {
    for (let n = li, i = 0; n && i < 80; n = n.previousElementSibling, i++) {
      const u = n.querySelector && n.querySelector('[id^="message-username-"]');
      if (u) return u.innerText.trim();
    }
    return null;
  };

  const parseLi = (li) => {
    const m = ID_RE.exec(li.id);
    if (!m) return null;
    const [, channelId, messageId] = m;
    const content = li.querySelector(`#message-content-${messageId}`);
    const time = li.querySelector("time[datetime]");
    return {
      id: messageId,
      channel_id: channelId,
      author_display: authorOf(li),
      timestamp: time ? time.getAttribute("datetime") : null,
      content: content ? content.innerText : "",
      media: [...new Set([...li.querySelectorAll("a[href], img[src]")]
        .map((e) => e.href || e.src).filter((u) => MEDIA_RE.test(u)))],
    };
  };

  const flushDom = () => {
    const messages = [];
    for (const li of pending) {
      const m = ID_RE.exec(li.id);
      if (!m || apiSeen.has(m[2]) || domSeen.has(m[2]) || !li.isConnected) continue;
      const parsed = parseLi(li);
      if (parsed && parsed.timestamp) { domSeen.add(parsed.id); messages.push(parsed); }
    }
    pending.clear();
    if (messages.length) post({ kind: "messages", source: "dom", url: null, context: context(), messages });
  };

  // チャンネルの先頭に出る「#〇〇へようこそ！」（id = chat-messages-<channel>-<channel>）を見たら、
  // そのチャンネルは最古まで取り終えたと記録する（巡回でも手動のスクロールでも）
  const topSeen = new Set();
  const TOP_RE = /^chat-messages-(\d+)-\1$/;
  const checkTop = (n) => {
    for (const el of [n, ...n.querySelectorAll('[id^="chat-messages-"]')]) {
      const m = el.id && TOP_RE.exec(el.id);
      if (m && !topSeen.has(m[1])) {
        topSeen.add(m[1]);
        post({ kind: "complete", channel_id: m[1], via: "top-marker", context: context() });
      }
    }
  };

  const watch = () => {
    new MutationObserver((records) => {
      for (const r of records) for (const n of r.addedNodes) {
        if (n.nodeType !== 1) continue;
        if (n.matches('li[id^="chat-messages-"]')) pending.add(n);
        checkTop(n);
        for (const li of n.querySelectorAll('li[id^="chat-messages-"]')) pending.add(li);
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
    // 描画直後は本文・時刻が未確定のことがあるので、少し待ってからまとめて読む
    setInterval(flushDom, 3000);
  };

  // --- 今どのチャンネルを見ているか（チャンネル名・サーバー名の対応づけ用） ---
  let last = "";
  setInterval(() => {
    const c = context();
    const key = c.path + "\n" + c.title;
    if (key !== last && c.path.startsWith("/channels/")) { last = key; post({ kind: "context", context: c }); }
  }, 2000);

  if (document.documentElement) watch();
  else document.addEventListener("DOMContentLoaded", watch, { once: true });
})();
