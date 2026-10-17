"""設定の読み込みと既定値マージ。

優先順位: CLI 引数 > config.toml > 既定値（SPEC §13/§14）。
CLI 層は CLI 引数のうち「明示指定されたもの」だけを overrides として渡すこと。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from .core.subtitle.postprocess import load_term_map
from .core.subtitle.reflow import SubtitleConfig
from .core.subtitle.style import SubtitleStyle, make_style, parse_hex_color

# サポートする出力形式。txt/json（segment）＋ srt/vtt/ass（字幕 Cue）。
SUPPORTED_FORMATS = ("txt", "json", "srt", "vtt", "ass")
SUPPORTED_DEVICES = ("auto", "cpu", "cuda")
SUPPORTED_ASR_BACKENDS = ("faster-whisper", "whisperx")
# LLM 後補正バックエンド
SUPPORTED_LLM_BACKENDS = ("ollama", "anthropic")
# PDF → Markdown 変換バックエンド
SUPPORTED_PDF_BACKENDS = ("pymupdf4llm", "docling")

_PUNCTUATION_MODES = ("keep", "space", "drop")
_LINE_BREAKS = ("balanced", "greedy")
_POSITIONS = ("bottom", "top")
_ALIGNMENTS = ("left", "center", "right")


@dataclass
class Config:
    """実効設定。既定は Apple Silicon / CPU 運用に合わせる。"""

    model: str = "turbo"
    language: str = "ja"
    asr_backend: str = "faster-whisper"  # faster-whisper / whisperx
    diarize: bool = False                # 話者分離（whisperx + HFトークン）
    hf_token: str = ""                   # HuggingFace トークン（話者分離用）
    formats: list[str] = field(default_factory=lambda: ["txt"])
    output_dir: str = ""  # 空なら入力と同じ場所
    device: str = "cpu"
    compute_type: str = "int8"
    timestamps: bool = False
    word_timestamps: bool = False
    preview: bool = False
    preview_height: int = 1080   # プレビューの高さ上限（アップスケールしない）。0で元のまま
    preview_fps: int = 30        # プレビューの fps 上限。0で元のまま
    beam_size: int = 5
    cpu_threads: int = 0  # 0 = 自動
    model_cache: str = ""
    # 精度向上（A: 前処理・語彙ヒント）
    denoise: bool = False                # 風切り音・ノイズ低減＋音量正規化
    vocab: list[str] = field(default_factory=list)  # 固有名詞ヒント → initial_prompt
    initial_prompt: str = ""             # 直接指定するプロンプト（vocab より優先）
    condition_on_previous_text: bool = True  # False でループ幻覚を抑制
    # 精度向上（C/D: LLM 後補正）
    llm_correct: bool = False            # LLM で誤変換・句読点を後補正
    llm_backend: str = "ollama"          # ollama（ローカル）/ anthropic（外部API・要オプトイン）
    llm_model: str = ""                  # 空なら backend ごとの既定
    llm_endpoint: str = "http://localhost:11434"  # ollama のエンドポイント
    llm_api_key: str = ""                # anthropic 用（環境変数 ANTHROPIC_API_KEY も可）
    ffmpeg: str = "ffmpeg"
    log_level: str = "info"
    log_file: str = ""
    # PDF → Markdown 変換
    pdf_backend: str = "pymupdf4llm"
    # 字幕テロップ
    subtitle: SubtitleConfig = field(default_factory=SubtitleConfig)
    subtitle_style: SubtitleStyle = field(default_factory=SubtitleStyle)

    def validate(self) -> None:
        """値の妥当性チェック。不正なら ValueError。"""
        bad = [f for f in self.formats if f not in SUPPORTED_FORMATS]
        if bad:
            raise ValueError(
                f"未対応の出力形式: {bad}（対応: {', '.join(SUPPORTED_FORMATS)}）。"
            )
        if not self.formats:
            raise ValueError("出力形式が指定されていません。")
        if self.device not in SUPPORTED_DEVICES:
            raise ValueError(
                f"未対応の device: {self.device}（対応: {', '.join(SUPPORTED_DEVICES)}）"
            )
        if self.asr_backend not in SUPPORTED_ASR_BACKENDS:
            raise ValueError(
                f"未対応の backend: {self.asr_backend}"
                f"（対応: {', '.join(SUPPORTED_ASR_BACKENDS)}）"
            )
        if self.pdf_backend not in SUPPORTED_PDF_BACKENDS:
            raise ValueError(
                f"未対応の pdf_backend: {self.pdf_backend}"
                f"（対応: {', '.join(SUPPORTED_PDF_BACKENDS)}）"
            )
        if self.llm_backend not in SUPPORTED_LLM_BACKENDS:
            raise ValueError(
                f"未対応の llm_backend: {self.llm_backend}"
                f"（対応: {', '.join(SUPPORTED_LLM_BACKENDS)}）"
            )
        if self.subtitle.punctuation_mode not in _PUNCTUATION_MODES:
            raise ValueError(
                f"未対応の punctuation_mode: {self.subtitle.punctuation_mode}"
                f"（対応: {', '.join(_PUNCTUATION_MODES)}）"
            )
        if self.subtitle.line_break not in _LINE_BREAKS:
            raise ValueError(
                f"未対応の line_break: {self.subtitle.line_break}"
                f"（対応: {', '.join(_LINE_BREAKS)}）"
            )
        if self.subtitle_style.position not in _POSITIONS:
            raise ValueError(
                f"未対応の position: {self.subtitle_style.position}"
                f"（対応: {', '.join(_POSITIONS)}）"
            )
        if self.subtitle_style.alignment not in _ALIGNMENTS:
            raise ValueError(
                f"未対応の alignment: {self.subtitle_style.alignment}"
                f"（対応: {', '.join(_ALIGNMENTS)}）"
            )
        # 色の形式チェック（不正なら ValueError）
        for c in (
            self.subtitle_style.text_color,
            self.subtitle_style.outline_color,
            self.subtitle_style.box_color,
        ):
            parse_hex_color(c)


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config(
    config_path: str | None = None,
    overrides: dict[str, Any] | None = None,
    *,
    sub_overrides: dict[str, Any] | None = None,
    style_overrides: dict[str, Any] | None = None,
) -> Config:
    """設定を構築する。

    Args:
        config_path: config.toml のパス。None かつ ./config.toml が存在すればそれを使う。
        overrides: CLI で明示指定されたトップレベル値（None でない項目のみ）。
        sub_overrides: `[subtitle]` の CLI 明示指定（None でない項目のみ）。
        style_overrides: `[subtitle.style]` の CLI 明示指定（None でない項目のみ）。

    Returns:
        マージ済み Config。
    """
    cfg = Config()

    # 1) config.toml
    path: Path | None = None
    if config_path:
        path = Path(config_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"設定ファイルが見つかりません: {path}")
    else:
        default_path = Path("config.toml")
        if default_path.exists():
            path = default_path

    if path is not None:
        cfg = _apply_toml(cfg, _load_toml(path))

    # 2) CLI overrides（明示指定のみ）
    if overrides:
        clean = {k: v for k, v in overrides.items() if v is not None}
        cfg = replace(cfg, **clean)
    if sub_overrides:
        _set_attrs(cfg.subtitle, sub_overrides)
        if sub_overrides.get("term_dictionary"):
            cfg.subtitle.term_map = load_term_map(sub_overrides["term_dictionary"])
    if style_overrides:
        so = dict(style_overrides)
        preset = so.pop("preset", None)
        if preset:  # CLI でプリセット指定 → その土台に置き換えて CLI 値を上乗せ
            cfg.subtitle_style = make_style(preset)
        _set_attrs(cfg.subtitle_style, so)

    cfg.validate()
    return cfg


def _set_attrs(target: Any, values: dict[str, Any]) -> None:
    """None でない値だけを既存フィールドへ代入する。"""
    for k, v in values.items():
        if v is not None and hasattr(target, k):
            setattr(target, k, v)


def _apply_toml(cfg: Config, data: dict[str, Any]) -> Config:
    """TOML の各セクションを Config にマージ。"""
    defaults = data.get("defaults", {})
    paths = data.get("paths", {})
    logging_ = data.get("logging", {})
    pdf = data.get("pdf", {})
    subtitle = data.get("subtitle", {})
    style = subtitle.get("style", {}) if isinstance(subtitle, dict) else {}

    updates: dict[str, Any] = {}
    if "model" in defaults:
        updates["model"] = defaults["model"]
    if "language" in defaults:
        updates["language"] = defaults["language"]
    if "asr_backend" in defaults:
        updates["asr_backend"] = defaults["asr_backend"]
    if "diarize" in defaults:
        updates["diarize"] = bool(defaults["diarize"])
    if "hf_token" in defaults:
        updates["hf_token"] = defaults["hf_token"]
    if "format" in defaults:
        fmt = defaults["format"]
        updates["formats"] = [fmt] if isinstance(fmt, str) else list(fmt)
    if "output_dir" in defaults:
        updates["output_dir"] = defaults["output_dir"]
    if "device" in defaults:
        updates["device"] = defaults["device"]
    if "compute_type" in defaults and defaults["compute_type"]:
        updates["compute_type"] = defaults["compute_type"]
    if "timestamps" in defaults:
        updates["timestamps"] = bool(defaults["timestamps"])
    if "word_timestamps" in defaults:
        updates["word_timestamps"] = bool(defaults["word_timestamps"])
    if "preview" in defaults:
        updates["preview"] = bool(defaults["preview"])
    if "preview_height" in defaults:
        updates["preview_height"] = int(defaults["preview_height"])
    if "preview_fps" in defaults:
        updates["preview_fps"] = int(defaults["preview_fps"])
    if "beam_size" in defaults:
        updates["beam_size"] = int(defaults["beam_size"])
    if "cpu_threads" in defaults:
        updates["cpu_threads"] = int(defaults["cpu_threads"])
    if "denoise" in defaults:
        updates["denoise"] = bool(defaults["denoise"])
    if "vocab" in defaults:
        v = defaults["vocab"]
        updates["vocab"] = [v] if isinstance(v, str) else list(v)
    if "initial_prompt" in defaults:
        updates["initial_prompt"] = defaults["initial_prompt"]
    if "condition_on_previous_text" in defaults:
        updates["condition_on_previous_text"] = bool(defaults["condition_on_previous_text"])

    llm = data.get("llm", {})
    if "correct" in llm:
        updates["llm_correct"] = bool(llm["correct"])
    if "backend" in llm:
        updates["llm_backend"] = llm["backend"]
    if "model" in llm:
        updates["llm_model"] = llm["model"]
    if "endpoint" in llm:
        updates["llm_endpoint"] = llm["endpoint"]
    if "api_key" in llm:
        updates["llm_api_key"] = llm["api_key"]

    if "model_cache" in paths:
        updates["model_cache"] = paths["model_cache"]
    if "ffmpeg" in paths:
        updates["ffmpeg"] = paths["ffmpeg"]

    if "level" in logging_:
        updates["log_level"] = logging_["level"]
    if "file" in logging_:
        updates["log_file"] = logging_["file"]

    if "backend" in pdf:
        updates["pdf_backend"] = pdf["backend"]

    cfg = replace(cfg, **updates)

    # [subtitle]（style を除く）
    if isinstance(subtitle, dict):
        sub_keys = {k: v for k, v in subtitle.items() if k != "style"}
        term_path = sub_keys.pop("term_dictionary", None)
        _set_attrs(cfg.subtitle, sub_keys)
        if term_path:
            cfg.subtitle.term_map = load_term_map(term_path)
    # [subtitle.style]
    if isinstance(style, dict):
        preset = style.get("preset")
        if preset:
            cfg.subtitle_style = make_style(preset)
        _set_attrs(cfg.subtitle_style, {k: v for k, v in style.items() if k != "preset"})

    return cfg
