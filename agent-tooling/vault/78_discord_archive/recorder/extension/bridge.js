// 拡張側（isolated world）。ページからの postMessage を受けて background へ渡すだけ。
window.addEventListener("message", (event) => {
  if (event.source !== window || !event.data || event.data.__dpr !== "discord-passive-recorder") return;
  try {
    chrome.runtime.sendMessage({ type: "record", payload: event.data.payload, captured_at: new Date().toISOString() });
  } catch {
    // 拡張を再読み込みした直後など。タブを再読み込みすれば直る
  }
});
