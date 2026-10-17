"""字幕テロップの見た目（スタイル）モデル。

このスタイルは **本ツールがレンダリングする ASS / ffmpeg 焼き込み**の値として扱う。
DaVinci Resolve は SRT に装飾を持てず、ASS 装飾も無視するため、Resolve では
インスペクタでトラックに適用（＋プリセット保存）する。Resolve 向けの推奨値は
docs/davinci-workflow.md を参照（縁取りは 5〜6 など、ASS 値とは尺度が異なる）。

既定は「白文字のみ（縁取り・帯なし）・小さめフォント」。数値は 1080p（PlayResY=1080）基準。
（縁取りが必要なら `preset=outline`、帯なら `preset=box` を選ぶ。）
"""

from __future__ import annotations

from dataclasses import dataclass

# ASS の既定レンダリング解像度。実動画へは libass / Resolve 側でスケールされる。
PLAY_RES_X = 1920
PLAY_RES_Y = 1080


@dataclass
class SubtitleStyle:
    """テロップの見た目。ASS `[V4+ Styles]` と ffmpeg force_style に写す。"""

    font_family: str = "Noto Sans JP"
    font_bold: bool = True
    font_italic: bool = False         # 斜体（和文は疑似オブリークで傾ける）
    font_size_pct: float = 4.0        # フレーム高に対する %（既定は控えめ）
    text_color: str = "#FFFFFF"       # 文字色
    outline: bool = False             # 既定は縁取りなし（白文字のみ）
    outline_color: str = "#000000"
    outline_width: float = 3.0        # ASS Outline（Resolve は 5〜6・別尺度）
    box: bool = False                 # 帯（背景）ON/OFF
    box_color: str = "#000000"
    box_opacity: int = 70             # 帯の不透明度 %（100=不透明）
    shadow: float = 0.0               # ASS Shadow（0=無効）
    position: str = "bottom"          # bottom / top
    margin_v_pct: float = 10.0        # 下（上）マージン %（セーフエリア）
    alignment: str = "center"         # left / center / right

    # ------------------------------------------------------------------ #
    # 派生値
    # ------------------------------------------------------------------ #
    def font_size_px(self, play_res_y: int = PLAY_RES_Y) -> int:
        return max(1, round(play_res_y * self.font_size_pct / 100))

    def margin_v_px(self, play_res_y: int = PLAY_RES_Y) -> int:
        return max(0, round(play_res_y * self.margin_v_pct / 100))

    def ass_alignment(self) -> int:
        """ASS の numpad 配置番号（1-9）。"""
        col = {"left": 1, "center": 2, "right": 3}.get(self.alignment, 2)
        row = 0 if self.position == "bottom" else 6  # bottom=1-3 / top=7-9
        return col + row

    def border_style(self) -> int:
        """1=縁取り+影 / 3=帯（塗り背景）。"""
        return 3 if self.box else 1


# 名前付きスタイルプリセット。--sub-preset / [subtitle.style].preset で選ぶ。
STYLE_PRESETS: dict[str, dict] = {
    # 白文字＋黒縁のみ（既定）。屋内・一人喋り向け。
    "outline": dict(box=False, outline=True, outline_width=3.0, shadow=0.0),
    # 白文字＋黒帯（不透明度70%）＋細い縁。屋外・旅Vlog で背景が煩雑でも視認性が高い。
    "box": dict(box=True, box_color="#000000", box_opacity=70,
                outline=True, outline_width=2.0, shadow=0.0),
    # 映画字幕風。細い縁＋弱い影、下やや上げ。punctuation_mode="space" と併用推奨。
    "cinema": dict(box=False, outline=True, outline_width=2.0, shadow=1.0,
                   margin_v_pct=12.0),
}


def make_style(preset: str | None = None, **overrides) -> SubtitleStyle:
    """プリセット名を土台に SubtitleStyle を作る（overrides で上書き）。"""
    base: dict = {}
    if preset:
        if preset not in STYLE_PRESETS:
            raise ValueError(
                f"未知のスタイルプリセット: {preset}"
                f"（対応: {', '.join(STYLE_PRESETS)}）"
            )
        base = dict(STYLE_PRESETS[preset])
    base.update({k: v for k, v in overrides.items() if v is not None})
    return SubtitleStyle(**base)


def parse_hex_color(value: str) -> tuple[int, int, int]:
    """'#RRGGBB' / 'RRGGBB' → (r, g, b)。"""
    s = value.strip().lstrip("#")
    if len(s) != 6:
        raise ValueError(f"色は #RRGGBB 形式で指定してください: {value!r}")
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError as exc:
        raise ValueError(f"色の解釈に失敗しました: {value!r}") from exc
    return r, g, b


def ass_color(hex_color: str, opacity_pct: int = 100) -> str:
    """'#RRGGBB' → ASS の '&HAABBGGRR'。opacity_pct 100=不透明。

    ASS のアルファは 00=不透明 / FF=透明。
    """
    r, g, b = parse_hex_color(hex_color)
    opacity_pct = max(0, min(100, opacity_pct))
    alpha = round((100 - opacity_pct) / 100 * 255)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"
