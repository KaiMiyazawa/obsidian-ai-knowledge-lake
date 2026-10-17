"""日本語 形態素解析アダプタ（字幕の語境界・改行に使う）。

インストール済みのライブラリを自動検出して使う（優先: fugashi → janome → sudachi）。
どれも無ければ None を返し、reflow 側は禁則ヒューリスティックにフォールバックする。
ローカル完結の方針に沿い、いずれも任意依存（`uv sync --extra morph` 等）。

公開API:
    get_tokenizer(mode) -> Tokenizer | None
    Tokenizer.analyze(text) -> list[(surface, pos)]
    Tokenizer.boundaries(text) -> set[int]        # 改行可能な文字インデックス
    Tokenizer.preferred_breaks(text) -> set[int]  # 助詞/記号の直後など優先位置
"""

from __future__ import annotations

from typing import Protocol

from ...logging_conf import get_logger

logger = get_logger()

# 直後で改行するのが自然な品詞（この品詞トークンの末尾＝優先分割位置）。
_PREFERRED_POS = ("助詞", "助動詞", "記号", "補助記号")

_CACHE: dict[str, "Tokenizer | None"] = {}


class Tokenizer(Protocol):
    name: str

    def analyze(self, text: str) -> list[tuple[str, str]]:
        """(表層形, 品詞大分類) の列を返す。"""
        ...

    def boundaries(self, text: str) -> set[int]:
        ...

    def preferred_breaks(self, text: str) -> set[int]:
        ...


class _BaseTokenizer:
    """analyze() だけ実装すれば boundaries/preferred を導出する土台。"""

    name = "base"

    def analyze(self, text: str) -> list[tuple[str, str]]:  # pragma: no cover
        raise NotImplementedError

    def boundaries(self, text: str) -> set[int]:
        idx = 0
        out: set[int] = set()
        for surface, _ in self.analyze(text):
            idx += len(surface)
            out.add(idx)
        out.discard(0)
        out.discard(len(text))
        return out

    def preferred_breaks(self, text: str) -> set[int]:
        idx = 0
        out: set[int] = set()
        for surface, pos in self.analyze(text):
            idx += len(surface)
            if pos in _PREFERRED_POS:
                out.add(idx)
        out.discard(0)
        out.discard(len(text))
        return out


class _FugashiTokenizer(_BaseTokenizer):
    name = "fugashi"

    def __init__(self) -> None:
        import fugashi

        self._tagger = fugashi.Tagger()

    def analyze(self, text: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for w in self._tagger(text):
            pos = getattr(getattr(w, "feature", None), "pos1", "") or ""
            out.append((w.surface, pos))
        return out


class _JanomeTokenizer(_BaseTokenizer):
    name = "janome"

    def __init__(self) -> None:
        from janome.tokenizer import Tokenizer as _JT

        self._t = _JT()

    def analyze(self, text: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for tok in self._t.tokenize(text):
            pos = tok.part_of_speech.split(",")[0]
            out.append((tok.surface, pos))
        return out


class _SudachiTokenizer(_BaseTokenizer):
    name = "sudachi"

    def __init__(self) -> None:
        from sudachipy import dictionary

        self._tok = dictionary.Dictionary().create()

    def analyze(self, text: str) -> list[tuple[str, str]]:
        from sudachipy import tokenizer as _sudachi_tok

        mode = _sudachi_tok.Tokenizer.SplitMode.A
        return [(m.surface(), m.part_of_speech()[0]) for m in self._tok.tokenize(text, mode)]


_LOADERS = (
    ("fugashi", _FugashiTokenizer),
    ("janome", _JanomeTokenizer),
    ("sudachi", _SudachiTokenizer),
)


def get_tokenizer(mode: str = "auto") -> "Tokenizer | None":
    """形態素解析器を取得する。

    mode:
        "off"           使わない（None）
        "auto"（既定）  利用可能なものを自動検出（無ければ None でフォールバック）
        "fugashi"/"janome"/"sudachi"  指定のものを使う（無ければ警告して None）
    """
    if mode == "off":
        return None
    if mode in _CACHE:
        return _CACHE[mode]

    candidates = _LOADERS if mode == "auto" else [c for c in _LOADERS if c[0] == mode]
    if not candidates and mode != "auto":
        logger.warning("未知の形態素解析モード: %s（禁則ヒューリスティックを使用）", mode)
        _CACHE[mode] = None
        return None

    for name, cls in candidates:
        try:
            tok = cls()
            logger.info("形態素解析: %s を使用", name)
            _CACHE[mode] = tok
            return tok
        except Exception as exc:  # noqa: BLE001 - 未インストール等はフォールバック
            logger.debug("形態素解析 %s は利用不可: %s", name, exc)

    if mode != "auto":
        logger.warning(
            "指定した形態素解析 %s が使えません。`uv sync --extra morph` 等で導入するか、"
            "禁則ヒューリスティックにフォールバックします。",
            mode,
        )
    _CACHE[mode] = None
    return None
