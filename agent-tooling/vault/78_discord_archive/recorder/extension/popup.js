const $ = (id) => document.getElementById(id);
const FIELDS = ["minDelaySec", "maxDelaySec", "restEveryLoads"];
const DEFAULTS = { minDelaySec: 5, maxDelaySec: 12, restEveryLoads: 300 };
const ALIVE_MS = 90000;

// サーバー一覧とチェック状態は、巡回の状態（crawl）とは別のキーに置く（巡回側の頻繁な書き込みと衝突させない）
const getLocal = async (key, fallback) => (await chrome.storage.local.get(key))[key] ?? fallback;

const activeDiscordTab = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab && /^https:\/\/discord\.com\//.test(tab.url || "") ? tab : null;
};

const send = async (msg) => {
  const tab = await activeDiscordTab();
  if (!tab) { $("status").textContent = "Discord のタブを前面にして、そのタブでポップアップを開いてください"; return null; }
  try {
    const res = await chrome.tabs.sendMessage(tab.id, msg);
    if (res && !res.ok) $("status").textContent = res.error;
    return res;
  } catch {
    $("status").textContent = "Discord のタブを再読み込みしてから、もう一度試してください";
    return null;
  }
};

const renderGuilds = async () => {
  const guilds = await getLocal("guilds", []);
  const selected = new Set(await getLocal("selectedGuilds", []));
  const crawl = await getLocal("crawl", {});
  const box = $("guilds");
  if (!guilds.length) return;
  box.textContent = "";
  for (const g of guilds) {
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = selected.has(g.id);
    cb.onchange = async () => {
      const cur = new Set(await getLocal("selectedGuilds", []));
      if (cb.checked) cur.add(g.id); else cur.delete(g.id);
      await chrome.storage.local.set({ selectedGuilds: [...cur] });
      updateCount();
    };
    const name = document.createElement("span");
    name.textContent = g.name;
    const prog = document.createElement("span");
    prog.className = "prog";
    prog.dataset.guild = g.id;
    label.append(cb, name, prog);
    box.append(label);
  }
  updateCount();
  updateProgress(crawl);
};

// サーバーごとの進み具合（完了チャンネル数 / 検出したチャンネル数）だけを書き換える
const updateProgress = async (crawl) => {
  crawl = crawl || await getLocal("crawl", {});
  for (const prog of document.querySelectorAll(".prog")) {
    const chans = (crawl.guildChannels || {})[prog.dataset.guild];
    if (!chans) { prog.textContent = ""; continue; }
    const done = chans.filter((c) => (crawl.done || {})[c]).length;
    prog.textContent = done === chans.length ? `完了 ${done}/${chans.length}` : `${done}/${chans.length}`;
  }
};

const updateCount = async () => {
  $("count").textContent = `${(await getLocal("selectedGuilds", [])).length} 件を選択`;
};

const renderStatus = async () => {
  const s = await getLocal("crawl", {});
  const done = Object.values(s.done || {});
  const top = done.filter((d) => d.result === "top").length;
  $("status").textContent =
    `状態: ${s.running ? "実行中" : "停止中"} ／ 今回の読み込み ${s.loads || 0} 回 ／ 429: ${s.rateHits || 0} 回\n` +
    `完了 ${top} ・飛ばした ${done.length - top}` + (s.total ? ` ／ 今回の対象 ${s.total} チャンネル` : "") + "\n\n" +
    (s.log || []).slice().reverse().join("\n");
};

(async () => {
  const s = await getLocal("crawl", {});
  for (const f of FIELDS) $(f).value = (s.settings && s.settings[f]) || DEFAULTS[f];
  $("skipCompleted").checked = !s.settings || s.settings.skipCompleted !== false; // 初期値はオン
  $("noScrollRest").checked = Boolean(s.settings && s.settings.noScrollRest);   // 初期値はオフ
  $("noChannelRest").checked = Boolean(s.settings && s.settings.noChannelRest); // 初期値はオフ
  await renderGuilds();
  renderStatus();
  setInterval(renderStatus, 1000);
  setInterval(() => updateProgress(), 3000);
})();

$("list").onclick = async () => {
  $("status").textContent = "サーバー一覧を取得中（閉じたフォルダを一時的に開く）…";
  const res = await send({ type: "list-guilds" });
  if (!res || !res.ok) return;
  await chrome.storage.local.set({ guilds: res.guilds });
  $("status").textContent = `${res.guilds.length} サーバーを取得`;
  renderGuilds();
};
$("all").onclick = async () => {
  await chrome.storage.local.set({ selectedGuilds: (await getLocal("guilds", [])).map((g) => g.id) });
  renderGuilds();
};
$("none").onclick = async () => {
  await chrome.storage.local.set({ selectedGuilds: [] });
  renderGuilds();
};

$("start").onclick = async () => {
  const guilds = await getLocal("guilds", []);
  const selected = new Set(await getLocal("selectedGuilds", []));
  const ids = guilds.map((g) => g.id).filter((id) => selected.has(id)); // 一覧の並び順で巡回する
  if (!ids.length) { $("status").textContent = "サーバーを1つ以上チェックしてください"; return; }
  send({
    type: "crawl-start",
    text: ids.join("\n"),
    settings: {
      ...Object.fromEntries(FIELDS.map((f) => [f, Number($(f).value) || DEFAULTS[f]])),
      skipCompleted: $("skipCompleted").checked,
      noScrollRest: $("noScrollRest").checked,
      noChannelRest: $("noChannelRest").checked,
    },
  });
};

// 停止は storage 経由（巡回がどの Discord タブで動いていても止まる）
$("stop").onclick = async () => {
  const s = await getLocal("crawl", {});
  // 動いているタブが無い（生存記録が古い）のに「実行中」が残っていたら、それも消す（勝手に自動再開させない）
  const alive = s.heartbeat && Date.now() - s.heartbeat.at < ALIVE_MS;
  await chrome.storage.local.set({ crawl: { ...s, stopRequested: true, ...(alive ? {} : { running: false }) } });
  renderStatus();
};
$("reset").onclick = async () => {
  const s = await getLocal("crawl", {});
  if (s.running && s.heartbeat && Date.now() - s.heartbeat.at < ALIVE_MS) return;
  await chrome.storage.local.set({ crawl: { ...s, running: false, done: {}, resume: {}, log: [], loads: 0, total: 0 } });
  renderStatus();
  renderGuilds();
};
