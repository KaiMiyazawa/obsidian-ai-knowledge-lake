"""Typer ベースの CLI エントリポイント。

サブコマンド構成:
    transcripter transcribe <音声/動画...>   音声・動画 → txt/json
    transcripter pdf        <PDF...>          PDF → Markdown

例:
    transcripter transcribe input.mp3 --language ja --format txt --output ./out
    transcripter pdf report.pdf --output ./out
    transcripter pdf ./pdfs --recursive --backend pymupdf4llm

設定の優先順位: CLI 引数 > config.toml > 既定値。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .config import load_config
from .core.audio import SUPPORTED_EXTS, check_ffmpeg
from .core.pdf import PDF_EXTS
from .core.pdf.converter import convert_pdf, make_backend as make_pdf_backend
from .core.transcriber import make_backend, transcribe_file
from .discovery import collect_inputs
from .errors import (
    EXIT_OK,
    EXIT_PARTIAL_FAILURE,
    EXIT_PRECONDITION,
    PdfConversionError,
    PreconditionError,
)
from .logging_conf import get_logger, setup_logging

app = typer.Typer(
    add_completion=True,
    help="ローカル完結の音声/動画 文字起こし & PDF→Markdown 変換ツール",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"transcripter {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    _version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True,
        help="バージョン表示",
    ),
) -> None:
    """ローカル完結の音声/動画 文字起こし & PDF→Markdown 変換ツール。"""


def _parse_formats(value: Optional[str]) -> Optional[list[str]]:
    if value is None:
        return None
    return [f.strip().lower() for f in value.split(",") if f.strip()]


def _parse_vocab(value: Optional[str]) -> Optional[list[str]]:
    if value is None:
        return None
    return [w.strip() for w in value.split(",") if w.strip()]


def _exit_for(ok: int, fail: int) -> None:
    """成功/失敗数から終了コードを決めて Exit する。"""
    if fail:
        raise typer.Exit(EXIT_PARTIAL_FAILURE)
    raise typer.Exit(EXIT_OK)


# --------------------------------------------------------------------------- #
# transcribe: 音声/動画 → txt/json
# --------------------------------------------------------------------------- #
@app.command()
def transcribe(
    inputs: list[Path] = typer.Argument(
        ..., help="入力ファイル or ディレクトリ（音声/動画・複数可）",
    ),
    model: Optional[str] = typer.Option(None, "--model", help="Whisper モデル名（既定 turbo）"),
    backend: Optional[str] = typer.Option(
        None, "--backend",
        help="推論バックエンド faster-whisper / whisperx（±50ms整列・話者分離。要 --extra whisperx）",
    ),
    diarize: Optional[bool] = typer.Option(
        None, "--diarize/--no-diarize", help="話者分離（whisperx + HFトークン）",
    ),
    hf_token: Optional[str] = typer.Option(
        None, "--hf-token", help="HuggingFace トークン（話者分離用。環境変数 HF_TOKEN も可）",
    ),
    speaker_labels: Optional[bool] = typer.Option(
        None, "--speaker-labels/--no-speaker-labels", help="字幕に話者名を前置",
    ),
    language: Optional[str] = typer.Option(
        None, "--language", "-l", help="言語コード（既定 ja、auto で自動判定）",
    ),
    format: Optional[str] = typer.Option(
        None, "--format", "-f", help="出力形式 txt,json をカンマ区切り（既定 txt）",
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="出力先ディレクトリ（既定: 入力と同じ場所）",
    ),
    device: Optional[str] = typer.Option(
        None, "--device", help="auto / cpu / cuda（Apple Silicon は cpu）",
    ),
    compute_type: Optional[str] = typer.Option(
        None, "--compute-type", help="int8 / float16 / int8_float16 / float32",
    ),
    vad: bool = typer.Option(False, "--vad/--no-vad", help="VAD（無音除去）の有効/無効"),
    timestamps: Optional[bool] = typer.Option(
        None, "--timestamps/--no-timestamps", help="txt に時刻を付与するか",
    ),
    word_timestamps: Optional[bool] = typer.Option(
        None, "--word-timestamps/--no-word-timestamps",
        help="word 単位時刻（字幕系フォーマットでは自動有効）",
    ),
    preview: Optional[bool] = typer.Option(
        None, "--preview/--no-preview", help="字幕を焼き込んだ確認用 mp4 を生成（動画のみ）",
    ),
    preview_height: Optional[int] = typer.Option(
        None, "--preview-height", help="プレビュー高さ上限px（0で元のまま・既定1080）",
    ),
    preview_fps: Optional[int] = typer.Option(
        None, "--preview-fps", help="プレビューfps上限（0で元のまま・既定30）",
    ),
    # --- 精度向上（前処理・語彙ヒント・LLM後補正） ---
    denoise: Optional[bool] = typer.Option(
        None, "--denoise/--no-denoise",
        help="風切り音・ノイズ低減＋音量正規化（屋外/アクションカメラ向け）",
    ),
    vocab: Optional[str] = typer.Option(
        None, "--vocab", help="固有名詞ヒントをカンマ区切りで（認識を語彙側へバイアス）",
    ),
    initial_prompt: Optional[str] = typer.Option(
        None, "--initial-prompt", help="認識ヒントの文（vocab より優先）",
    ),
    condition_previous: Optional[bool] = typer.Option(
        None, "--condition-previous/--no-condition-previous",
        help="直前テキストへの条件付け（--no- でループ幻覚を抑制）",
    ),
    accurate: bool = typer.Option(
        False, "--accurate",
        help="精度優先プリセット（model=large-v3・VAD・条件付けOFF・ノイズ低減）",
    ),
    llm_correct: Optional[bool] = typer.Option(
        None, "--llm-correct/--no-llm-correct",
        help="LLMで誤変換・句読点を後補正（既定 backend=ollama・ローカル）",
    ),
    llm_backend: Optional[str] = typer.Option(
        None, "--llm-backend", help="ollama（ローカル）/ anthropic（外部API・要オプトイン）",
    ),
    llm_model: Optional[str] = typer.Option(
        None, "--llm-model", help="後補正モデル名（空で backend 既定）",
    ),
    llm_endpoint: Optional[str] = typer.Option(
        None, "--llm-endpoint", help="Ollama エンドポイント（既定 http://localhost:11434）",
    ),
    llm_api_key: Optional[str] = typer.Option(
        None, "--llm-api-key", help="Anthropic APIキー（環境変数 ANTHROPIC_API_KEY も可）",
    ),
    # --- 字幕整形（[subtitle]） ---
    sub_max_line_chars: Optional[int] = typer.Option(
        None, "--sub-max-line-chars", help="字幕1行の最大文字数（既定14）",
    ),
    sub_max_lines: Optional[int] = typer.Option(
        None, "--sub-max-lines", help="字幕の最大行数（既定2）",
    ),
    sub_max_chars: Optional[int] = typer.Option(
        None, "--sub-max-chars", help="字幕1枚の最大文字数（既定28）",
    ),
    sub_min_duration: Optional[float] = typer.Option(
        None, "--sub-min-duration", help="字幕の最短表示秒（既定1.2）",
    ),
    sub_max_duration: Optional[float] = typer.Option(
        None, "--sub-max-duration", help="字幕の最長表示秒（既定6.0）",
    ),
    sub_max_cps: Optional[float] = typer.Option(
        None, "--sub-max-cps", help="1秒あたり最大文字数（読み速度・既定13）",
    ),
    sub_gap_split: Optional[float] = typer.Option(
        None, "--sub-gap-split", help="この無音秒数以上で字幕を分割（既定0.8）",
    ),
    sub_line_break: Optional[str] = typer.Option(
        None, "--sub-line-break", help="改行戦略 balanced / greedy",
    ),
    sub_morph: Optional[str] = typer.Option(
        None, "--sub-morph",
        help="形態素解析で語境界改行 auto/off/fugashi/janome/sudachi（要 --extra morph）",
    ),
    sub_punctuation: Optional[str] = typer.Option(
        None, "--sub-punctuation", help="句読点 keep / space / drop",
    ),
    strip_fillers: Optional[bool] = typer.Option(
        None, "--strip-fillers/--no-strip-fillers", help="フィラー（えー/あの等）を除去",
    ),
    term_dict: Optional[Path] = typer.Option(
        None, "--term-dict", help="用語/表記の置換CSV（誤,正）",
    ),
    # --- 字幕スタイル（[subtitle.style]） ---
    sub_preset: Optional[str] = typer.Option(
        None, "--sub-preset", help="スタイルプリセット outline（白+黒縁）/ box（帯）/ cinema",
    ),
    sub_font: Optional[str] = typer.Option(None, "--sub-font", help="フォント名"),
    sub_font_size: Optional[float] = typer.Option(
        None, "--sub-font-size", help="フォントサイズ（フレーム高に対する%）",
    ),
    sub_italic: Optional[bool] = typer.Option(
        None, "--sub-italic/--no-sub-italic", help="斜体（和文は疑似オブリーク）",
    ),
    sub_box: Optional[bool] = typer.Option(
        None, "--sub-box/--no-sub-box", help="帯（背景）の有無",
    ),
    sub_box_opacity: Optional[int] = typer.Option(
        None, "--sub-box-opacity", help="帯の不透明度%（既定70）",
    ),
    sub_position: Optional[str] = typer.Option(
        None, "--sub-position", help="字幕位置 bottom / top",
    ),
    recursive: bool = typer.Option(
        False, "--recursive", "-r", help="ディレクトリを再帰探索",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="既存の出力を上書き"),
    beam_size: Optional[int] = typer.Option(None, "--beam-size", help="デコードビーム幅"),
    cpu_threads: Optional[int] = typer.Option(None, "--cpu-threads", help="CPU スレッド数"),
    config_path: Optional[Path] = typer.Option(
        None, "--config", help="設定ファイルパス（既定: ./config.toml があれば使用）",
    ),
    log_level: Optional[str] = typer.Option(
        None, "--log-level", help="debug / info / warning / error",
    ),
    log_file: Optional[Path] = typer.Option(None, "--log-file", help="ログ出力ファイル"),
) -> None:
    """音声/動画ファイルを文字起こしする（→ txt/json）。"""
    overrides = {
        "model": model,
        "asr_backend": backend,
        "diarize": diarize,
        "hf_token": hf_token or os.environ.get("HF_TOKEN") or None,
        "language": language,
        "formats": _parse_formats(format),
        "output_dir": str(output) if output is not None else None,
        "device": device,
        "compute_type": compute_type,
        "timestamps": timestamps,
        "word_timestamps": word_timestamps,
        "preview": preview,
        "preview_height": preview_height,
        "preview_fps": preview_fps,
        "beam_size": beam_size,
        "cpu_threads": cpu_threads,
        "denoise": denoise,
        "vocab": _parse_vocab(vocab),
        "initial_prompt": initial_prompt,
        "condition_on_previous_text": condition_previous,
        "llm_correct": llm_correct,
        "llm_backend": llm_backend,
        "llm_model": llm_model,
        "llm_endpoint": llm_endpoint,
        "llm_api_key": llm_api_key or os.environ.get("ANTHROPIC_API_KEY") or None,
        "log_level": log_level,
        "log_file": str(log_file) if log_file is not None else None,
    }
    # --accurate: 精度優先プリセット（明示指定があればそちらを尊重）
    if accurate:
        if model is None:
            overrides["model"] = "large-v3"
        if condition_previous is None:
            overrides["condition_on_previous_text"] = False
        if denoise is None:
            overrides["denoise"] = True
        vad = vad or True
    sub_overrides = {
        "max_chars_per_line": sub_max_line_chars,
        "max_lines": sub_max_lines,
        "max_chars_per_cue": sub_max_chars,
        "min_duration_s": sub_min_duration,
        "max_duration_s": sub_max_duration,
        "max_cps": sub_max_cps,
        "gap_split_s": sub_gap_split,
        "line_break": sub_line_break,
        "morph": sub_morph,
        "punctuation_mode": sub_punctuation,
        "strip_fillers": strip_fillers,
        "speaker_labels": speaker_labels,
        "term_dictionary": str(term_dict) if term_dict is not None else None,
    }
    style_overrides = {
        "preset": sub_preset,
        "font_family": sub_font,
        "font_size_pct": sub_font_size,
        "font_italic": sub_italic,
        "box": sub_box,
        "box_opacity": sub_box_opacity,
        "position": sub_position,
    }
    try:
        cfg = load_config(
            str(config_path) if config_path else None,
            overrides=overrides,
            sub_overrides=sub_overrides,
            style_overrides=style_overrides,
        )
    except (FileNotFoundError, ValueError) as exc:
        setup_logging()
        get_logger().error(str(exc))
        raise typer.Exit(EXIT_PRECONDITION)

    logger = setup_logging(cfg.log_level, cfg.log_file or None)

    try:
        check_ffmpeg(cfg.ffmpeg)
    except PreconditionError as exc:
        logger.error(str(exc))
        raise typer.Exit(EXIT_PRECONDITION)

    files = collect_inputs(list(inputs), exts=SUPPORTED_EXTS, recursive=recursive)
    if not files:
        logger.error("処理対象の対応ファイルが見つかりませんでした。")
        raise typer.Exit(EXIT_PRECONDITION)

    logger.info(
        "対象 %d ファイル / モデル=%s / 言語=%s / 形式=%s / device=%s/%s / VAD=%s",
        len(files), cfg.model, cfg.language, ",".join(cfg.formats),
        cfg.device, cfg.compute_type, "on" if vad else "off",
    )

    # モデルは 1 回ロードして全ファイルで再利用（backend は設定で切替）
    backend = make_backend(cfg)

    ok_count = fail_count = 0
    for f in files:
        outcome = transcribe_file(f, backend, cfg, vad=vad, overwrite=overwrite)
        if outcome.ok:
            ok_count += 1
        else:
            fail_count += 1

    logger.info("完了: 成功 %d / 失敗 %d", ok_count, fail_count)
    _exit_for(ok_count, fail_count)


# --------------------------------------------------------------------------- #
# pdf: PDF → Markdown
# --------------------------------------------------------------------------- #
@app.command()
def pdf(
    inputs: list[Path] = typer.Argument(
        ..., help="入力ファイル or ディレクトリ（PDF・複数可）",
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="出力先ディレクトリ（既定: 入力と同じ場所）",
    ),
    backend: Optional[str] = typer.Option(
        None, "--backend", "-b",
        help="変換バックエンド pymupdf4llm / docling（既定 pymupdf4llm）",
    ),
    recursive: bool = typer.Option(
        False, "--recursive", "-r", help="ディレクトリを再帰探索",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="既存の .md を上書き"),
    config_path: Optional[Path] = typer.Option(
        None, "--config", help="設定ファイルパス（既定: ./config.toml があれば使用）",
    ),
    log_level: Optional[str] = typer.Option(
        None, "--log-level", help="debug / info / warning / error",
    ),
    log_file: Optional[Path] = typer.Option(None, "--log-file", help="ログ出力ファイル"),
) -> None:
    """PDF ファイルを Markdown に変換する（ローカル完結）。"""
    overrides = {
        "output_dir": str(output) if output is not None else None,
        "pdf_backend": backend,
        "log_level": log_level,
        "log_file": str(log_file) if log_file is not None else None,
    }
    try:
        cfg = load_config(str(config_path) if config_path else None, overrides=overrides)
    except (FileNotFoundError, ValueError) as exc:
        setup_logging()
        get_logger().error(str(exc))
        raise typer.Exit(EXIT_PRECONDITION)

    logger = setup_logging(cfg.log_level, cfg.log_file or None)

    files = collect_inputs(list(inputs), exts=PDF_EXTS, recursive=recursive)
    if not files:
        logger.error("処理対象の PDF が見つかりませんでした。")
        raise typer.Exit(EXIT_PRECONDITION)

    try:
        pdf_backend = make_pdf_backend(cfg.pdf_backend)
    except PdfConversionError as exc:
        logger.error(str(exc))
        raise typer.Exit(EXIT_PRECONDITION)

    logger.info(
        "対象 %d ファイル / バックエンド=%s", len(files), cfg.pdf_backend,
    )

    out_dir = Path(cfg.output_dir).expanduser() if cfg.output_dir else None
    ok_count = fail_count = 0
    for f in files:
        outcome = convert_pdf(f, pdf_backend, out_dir, overwrite=overwrite)
        if outcome.ok:
            ok_count += 1
        else:
            fail_count += 1

    logger.info("完了: 成功 %d / 失敗 %d", ok_count, fail_count)
    _exit_for(ok_count, fail_count)


# --------------------------------------------------------------------------- #
# serve: ローカル Web UI（ドラッグ&ドロップ字幕生成）
# --------------------------------------------------------------------------- #
@app.command()
def digest(
    video: Path = typer.Argument(..., help="動画ファイル"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="成果物フォルダ（既定: 動画と同じ場所の <動画名>_digest/）",
    ),
    interval: float = typer.Option(10.0, "--interval", help="静止画・章の間隔（秒）"),
    width: int = typer.Option(640, "--width", help="静止画の幅（px）"),
    no_transcribe: bool = typer.Option(
        False, "--no-transcribe", help="文字起こしを省略し、静止画だけにする（速い）",
    ),
    language: Optional[str] = typer.Option(None, "--language", "-l", help="言語（既定 ja）"),
    vocab: Optional[str] = typer.Option(
        None, "--vocab", help="固有名詞ヒント（カンマ区切り。地名・人名の認識を改善）",
    ),
    denoise: Optional[bool] = typer.Option(
        None, "--denoise/--no-denoise", help="風切り音・ノイズ低減（屋外/アクションカメラ向け）",
    ),
    vad: bool = typer.Option(
        True, "--vad/--no-vad", help="VAD（無音除去。既定オン）",
    ),
    config_path: Optional[Path] = typer.Option(None, "--config", help="設定ファイルパス"),
) -> None:
    """動画を「AI が中身を把握できる形」にする（時刻付き発話＋静止画＋コンタクトシート）。

    成果物は ``digest.md``（章ごとの静止画パスと発話）、``sheet_NN.jpg``、``frames/``、
    ``<動画名>.json``（文字起こし）。すべてローカル処理で外部送信しない。
    """
    from .core.digest import DigestOptions, build_digest, load_segments

    cfg = load_config(
        str(config_path) if config_path else None,
        overrides={
            "formats": ["json"],
            "language": language,
            "vocab": _parse_vocab(vocab),
            "denoise": denoise,
        },
    )
    logger = setup_logging(cfg.log_level, cfg.log_file or None)
    try:
        check_ffmpeg(cfg.ffmpeg)
    except PreconditionError as exc:
        logger.error(str(exc))
        raise typer.Exit(EXIT_PRECONDITION)
    if not video.is_file():
        logger.error("動画が見つかりません: %s", video)
        raise typer.Exit(EXIT_PRECONDITION)

    out_dir = output or video.with_name(f"{video.stem}_digest")
    out_dir.mkdir(parents=True, exist_ok=True)

    segments = None
    if not no_transcribe:
        cfg.output_dir = str(out_dir)
        outcome = transcribe_file(
            video, make_backend(cfg), cfg, vad=vad, overwrite=True, show_progress=True
        )
        if not outcome.ok:
            logger.error("文字起こしに失敗しました: %s", outcome.error)
            raise typer.Exit(EXIT_PARTIAL_FAILURE)
        segments = load_segments(out_dir / f"{video.stem}.json")

    try:
        md = build_digest(
            video, out_dir,
            DigestOptions(interval_s=interval, frame_width=width, ffmpeg=cfg.ffmpeg),
            segments,
        )
    except (ValueError, OSError) as exc:
        logger.error("ダイジェスト作成に失敗: %s", exc)
        raise typer.Exit(EXIT_PARTIAL_FAILURE)
    typer.echo(str(md))
    raise typer.Exit(EXIT_OK)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="バインドするホスト"),
    port: int = typer.Option(8765, "--port", help="ポート"),
    output: Path = typer.Option(
        Path("./webui-outputs"), "--output", "-o", help="成果物の保存先",
    ),
) -> None:
    """ローカル Web UI を起動する（要 `--extra webui`）。すべてローカル処理。"""
    setup_logging()
    logger = get_logger()
    try:
        import uvicorn

        from .webui.app import create_app
    except ImportError:
        logger.error(
            "Web UI の依存が未導入です。`uv sync --extra webui` を実行してください。"
        )
        raise typer.Exit(EXIT_PRECONDITION)

    app_ = create_app(output)
    logger.info("Web UI を起動: http://%s:%d  （成果物: %s）", host, port, output)
    uvicorn.run(app_, host=host, port=port)


if __name__ == "__main__":
    app()
