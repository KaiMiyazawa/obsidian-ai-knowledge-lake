#!/usr/bin/env python
"""DaVinci Resolve: SRT を現在のタイムラインに取り込む補助スクリプト。

transcripter が出力した `.srt` を Resolve の字幕トラックとして読み込むための
**Resolve 内スクリプト**。見た目（フォント/帯/縁）は取り込み後にインスペクタで
トラックへ適用し、プリセット保存して再利用する（docs/davinci-workflow.md）。

── 前提・制限（重要）─────────────────────────────────────────────
- **Resolve Studio** 推奨。無料版は外部プロセスからのスクリプティングAPIに制限があり、
  Resolve 内の Console/スクリプトメニューからの実行が確実。
- Resolve のバージョンによって字幕インポートAPIの対応が異なる。取り込みが失敗する
  場合は手動（メディアプールへ `.srt` をドラッグ、または File > Import > Subtitle）で
  取り込むこと。本スクリプトはそれを自動化する best-effort。
- 本スクリプトは transcripter のテスト対象外（Resolve 実機が必要なため）。

── 使い方 ───────────────────────────────────────────────────────
1) 対象プロジェクト/タイムラインを Resolve で開く。
2) Resolve の Workspace > Console、または スクリプトメニューから実行:
      SRT_PATH=/path/to/video.srt  を環境変数か下の SRT_PATH で指定。
   もしくは端末から（Studio・環境変数設定済みの場合）:
      python scripts/davinci_import_srt.py /path/to/video.srt
"""

from __future__ import annotations

import os
import sys


def _get_resolve():
    """Resolve アプリのハンドルを取得（内部 `resolve` 変数 or Python API）。"""
    if "resolve" in globals():  # Resolve 内 Console 実行時に注入される
        return globals()["resolve"]
    try:
        import DaVinciResolveScript as dvr  # Resolve 同梱モジュール
        return dvr.scriptapp("Resolve")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Resolve に接続できません。Resolve Studio を起動し、"
            "スクリプティングを有効化（環境変数 RESOLVE_SCRIPT_API/…）してください。\n"
            f"  詳細: {exc}"
        )


def import_srt(srt_path: str) -> None:
    if not os.path.exists(srt_path):
        raise SystemExit(f"SRT が見つかりません: {srt_path}")

    resolve = _get_resolve()
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project is None:
        raise SystemExit("開いているプロジェクトがありません。")
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise SystemExit("開いているタイムラインがありません。")

    media_pool = project.GetMediaPool()
    resolve.OpenPage("edit")

    # まずメディアプールへ取り込み（字幕クリップとして入る）
    imported = media_pool.ImportMedia([srt_path])
    if not imported:
        raise SystemExit(
            "ImportMedia が失敗しました。手動で取り込んでください"
            "（メディアプールへドラッグ / File > Import > Subtitle）。"
        )

    print(f"取り込み成功: {srt_path}")
    print(
        "次の手順（手動）:\n"
        "  1) 取り込んだ字幕をタイムラインの字幕トラックへ配置\n"
        "  2) 字幕トラックを選択し、インスペクタで見た目を適用\n"
        "     （保存済みトラックプリセットがあれば 1 クリック）\n"
        "  3) 焼き込みプレビュー（*_preview.mp4）と見比べて誤字・改行のみ微修正"
    )


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SRT_PATH", "")
    if not path:
        raise SystemExit("使い方: davinci_import_srt.py <SRTパス>  (または SRT_PATH env)")
    import_srt(path)
