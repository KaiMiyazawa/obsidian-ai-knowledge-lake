"""FastAPI アプリ本体。ローカルで字幕生成を行う最小 UI。

依存は任意（`--extra webui`）。この module は `serve` 実行時にだけ import する。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from ..config import load_config
from ..core.audio import check_ffmpeg
from ..core.transcriber import make_backend, transcribe_file
from ..logging_conf import get_logger

logger = get_logger()

_INDEX_HTML = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>transcripter — 字幕テロップ生成</title>
<style>
 :root{color-scheme:light dark}
 body{font-family:system-ui,-apple-system,"Hiragino Sans",sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;line-height:1.6}
 h1{font-size:1.4rem} label{display:block;margin:.6rem 0 .2rem;font-size:.9rem;opacity:.85}
 #drop{border:2px dashed #888;border-radius:12px;padding:2.5rem 1rem;text-align:center;cursor:pointer;transition:.15s}
 #drop.over{border-color:#3b82f6;background:rgba(59,130,246,.08)}
 select,button{font:inherit;padding:.4rem .6rem;border-radius:8px}
 .row{display:flex;gap:1rem;flex-wrap:wrap} .row>div{flex:1;min-width:140px}
 button{background:#3b82f6;color:#fff;border:0;cursor:pointer;padding:.6rem 1.2rem;margin-top:1rem}
 button:disabled{opacity:.5;cursor:progress}
 #out{margin-top:1.5rem} #out a{display:block;margin:.2rem 0}
 video{max-width:100%;margin-top:1rem;border-radius:8px}
 .muted{opacity:.6;font-size:.85rem}
</style></head><body>
<h1>🎬 transcripter — 字幕テロップ生成</h1>
<p class="muted">動画/音声をドロップ → 字幕(SRT/ASS)と焼き込みプレビューを生成。すべてローカル処理。</p>
<div id="drop">ここにファイルをドラッグ&ドロップ<br><span class="muted">またはクリックして選択</span>
 <input id="file" type="file" accept="audio/*,video/*" hidden></div>
<div class="row">
 <div><label>出力形式</label><select id="format">
   <option value="srt">SRT（DaVinci用）</option>
   <option value="srt,ass">SRT + ASS</option>
   <option value="srt,vtt,ass">SRT + VTT + ASS</option>
 </select></div>
 <div><label>スタイル</label><select id="preset">
   <option value="outline">白文字＋黒縁</option>
   <option value="box">帯つき（黒70%）</option>
   <option value="cinema">映画字幕風</option>
 </select></div>
 <div><label>プレビュー(焼込)</label><select id="preview">
   <option value="true">生成する（動画のみ）</option>
   <option value="false">生成しない</option>
 </select></div>
</div>
<button id="go" disabled>字幕を生成</button>
<div id="out"></div>
<script>
const drop=document.getElementById('drop'),fileIn=document.getElementById('file'),go=document.getElementById('go'),out=document.getElementById('out');
let file=null;
function setFile(f){file=f;drop.innerHTML=f?('選択: <b>'+f.name+'</b>'):'ここにドラッグ&ドロップ';go.disabled=!f;}
drop.onclick=()=>fileIn.click();
fileIn.onchange=e=>setFile(e.target.files[0]);
drop.ondragover=e=>{e.preventDefault();drop.classList.add('over');};
drop.ondragleave=()=>drop.classList.remove('over');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('over');setFile(e.dataTransfer.files[0]);};
go.onclick=async()=>{
 if(!file)return; go.disabled=true; go.textContent='生成中…（数分かかります）'; out.innerHTML='';
 const fd=new FormData();
 fd.append('file',file);
 fd.append('format',document.getElementById('format').value);
 fd.append('preset',document.getElementById('preset').value);
 fd.append('preview',document.getElementById('preview').value);
 try{
  const r=await fetch('/api/transcribe',{method:'POST',body:fd});
  const j=await r.json();
  if(!j.ok){out.innerHTML='<p style="color:#e11">失敗: '+(j.error||'不明')+'</p>';}
  else{
   out.innerHTML='<h3>✅ 生成完了</h3>';
   j.outputs.forEach(u=>{out.innerHTML+='<a href="'+u+'" download>⬇ '+u.split('/').pop()+'</a>';});
   const mp4=j.outputs.find(u=>u.endsWith('.mp4'));
   if(mp4)out.innerHTML+='<video src="'+mp4+'" controls></video>';
  }
 }catch(e){out.innerHTML='<p style="color:#e11">エラー: '+e+'</p>';}
 go.disabled=false; go.textContent='字幕を生成';
};
</script></body></html>"""


def create_app(output_root: Path) -> FastAPI:
    """FastAPI アプリを生成する。output_root に成果物を保存し /files で配信。"""
    output_root = Path(output_root).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="transcripter web UI")
    app.mount("/files", StaticFiles(directory=str(output_root)), name="files")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _INDEX_HTML

    @app.post("/api/transcribe")
    async def api_transcribe(
        file: UploadFile,
        format: str = Form("srt"),
        preset: str = Form("outline"),
        preview: str = Form("false"),
    ) -> JSONResponse:
        job = uuid.uuid4().hex[:8]
        job_dir = output_root / job
        job_dir.mkdir(parents=True, exist_ok=True)
        in_path = job_dir / (file.filename or "input")
        in_path.write_bytes(await file.read())

        want_preview = preview.lower() in ("1", "true", "yes", "on")
        try:
            cfg = load_config(
                overrides={
                    "formats": [f.strip() for f in format.split(",") if f.strip()],
                    "output_dir": str(job_dir),
                    "preview": want_preview,
                },
                style_overrides={"preset": preset},
            )
            check_ffmpeg(cfg.ffmpeg)
            backend = make_backend(cfg)
            outcome = await run_in_threadpool(
                transcribe_file, in_path, backend, cfg,
                vad=True, overwrite=True, show_progress=False,
            )
        except Exception as exc:  # noqa: BLE001 - UI にエラーを返す
            logger.exception("web UI 生成失敗")
            return JSONResponse({"ok": False, "error": str(exc)})

        if not outcome.ok:
            return JSONResponse({"ok": False, "error": outcome.error or "生成に失敗しました"})
        urls = [f"/files/{job}/{p.name}" for p in outcome.outputs]
        return JSONResponse({"ok": True, "outputs": urls})

    return app
