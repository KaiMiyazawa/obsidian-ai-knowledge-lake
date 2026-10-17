"""字幕整形エンジン: Whisper の segment/word 時刻 → 読みやすい Cue 列。

方針（docs/subtitle-telop-plan.md §4）:
  1) word 列を、無音ギャップ / 文末句読点 / 文字数 / 最大表示秒 で cue に分割
  2) 各 cue を最大文字数・最大行数で改行（句読点・助詞境界を優先）
  3) 最小表示秒・読み速度(cps) で表示時間を補正、重なりをクランプ

word_timestamps が無い場合は segment 全体を 1 疑似 word として扱いフォールバックする。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..backend import Segment, Word
from .model import Cue
from .morph import Tokenizer, get_tokenizer
from .postprocess import (
    DEFAULT_FILLERS,
    apply_punctuation_mode,
    apply_term_map,
    is_filler,
)

# 文末とみなす記号（ここで cue を切る）。読点「、」は含めない。
_SENTENCE_END = "。！？!?"
# 改行位置として好ましい境界（この文字の直後で折り返す）。
_BREAK_AFTER = set("、。！？!?…" "はがをにでともへやのからまでねよわ")
# 小書き仮名（拗音・促音）。語の途中なので、直前で切ったり行頭に置いたりしない。
_SMALL_KANA = set("ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ")
# 行頭禁則: 行の先頭に来てはいけない文字（小書き仮名・長音・閉じ括弧・句読点）。
_LEADING_PROHIBITED = _SMALL_KANA | set("ーｰ〜ー々ゝゞヽヾ、。，．・！？!?）)｝」』】〕〉》”’｣")
# 行末禁則: 行の末尾に来てはいけない文字（開き括弧）。
_TRAILING_PROHIBITED = set("（(｛「『【〔〈《“‘｢")
# 表示時間補正で隣接 cue との間に空ける最小ギャップ（秒）。
_MIN_GAP = 0.04


@dataclass
class SubtitleConfig:
    """字幕整形パラメータ（config `[subtitle]` / CLI に対応）。"""

    max_chars_per_line: int = 14
    max_lines: int = 1                     # 既定は字幕1枚=1行
    # 1文がなるべく1字幕に収まる長さ。句読点(。！？)では常に切るので、
    # この上限は「句点の無い一続きの発話をどこまで1枚に載せるか」を決める。
    max_chars_per_cue: int = 32
    min_cue_chars: int = 3                 # これ未満の極小 cue は近い隣へ結合
    min_duration_s: float = 1.2
    max_duration_s: float = 6.0
    max_cps: float = 13.0
    gap_split_s: float = 0.8
    split_on_punctuation: bool = True
    split_on_speaker: bool = True         # 話者が変わったら字幕を分ける（話者分離時）
    speaker_labels: bool = False          # 字幕に話者名を前置する（話者分離時）
    line_break: str = "balanced"          # balanced / greedy
    morph: str = "auto"                   # auto / off / fugashi / janome / sudachi
    punctuation_mode: str = "keep"        # keep / space / drop
    strip_fillers: bool = False
    term_map: list[tuple[str, str]] = field(default_factory=list)
    fillers: set[str] = field(default_factory=lambda: set(DEFAULT_FILLERS))


def _vlen(text: str) -> int:
    """表示幅の目安。空白・改行を除いた文字数。"""
    return sum(1 for ch in text if not ch.isspace())


def _majority_speaker(words: list[Word]) -> str | None:
    """グループ内で最も多く出る話者ラベル（無ければ None）。"""
    counts: dict[str, int] = {}
    for w in words:
        if w.speaker:
            counts[w.speaker] = counts.get(w.speaker, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _collect_words(segments: list[Segment], cfg: SubtitleConfig) -> list[Word]:
    """全 segment を word 列へ平坦化。word が無ければ segment を疑似 word 化。"""
    words: list[Word] = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                if not w.text.strip():
                    continue
                if cfg.strip_fillers and is_filler(w.text, cfg.fillers):
                    continue
                words.append(w)
        else:
            text = seg.text.strip()
            if text:
                words.append(
                    Word(start=seg.start, end=seg.end, text=seg.text, speaker=seg.speaker)
                )
    return words


def _group_words(words: list[Word], cfg: SubtitleConfig) -> list[list[Word]]:
    """境界条件で word 列を cue 単位のまとまりへ分割する。"""
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            prev = cur[-1]
            gap = w.start - prev.end
            cur_text = "".join(x.text for x in cur)
            would_chars = _vlen(cur_text) + _vlen(w.text)
            span = w.end - cur[0].start
            # 小書き仮名で始まる語は前の語の続き → ここで切らない（行頭に来ないように）
            lead = w.text.strip()[:1]
            is_continuation = lead in _SMALL_KANA
            speaker_changed = (
                cfg.split_on_speaker
                and w.speaker is not None
                and prev.speaker is not None
                and w.speaker != prev.speaker
            )
            if speaker_changed or (
                not is_continuation
                and (
                    gap >= cfg.gap_split_s
                    or would_chars > cfg.max_chars_per_cue
                    or span > cfg.max_duration_s
                )
            ):
                groups.append(cur)
                cur = []
        cur.append(w)
        if cfg.split_on_punctuation:
            tail = w.text.strip()
            if tail and tail[-1] in _SENTENCE_END:
                groups.append(cur)
                cur = []
    if cur:
        groups.append(cur)
    return groups


def _breakable(text: str, i: int) -> bool:
    """位置 i（line2 の先頭）で改行してよいか。行頭・行末禁則を考慮。"""
    if i <= 0 or i >= len(text):
        return False
    if text[i] in _LEADING_PROHIBITED:      # 行頭に来てはいけない文字
        return False
    if text[i - 1] in _TRAILING_PROHIBITED:  # 行末に来てはいけない文字
        return False
    return True


def _choose_split(
    text: str,
    cfg: SubtitleConfig,
    breaks: set[int] | None = None,
    preferred: set[int] | None = None,
) -> int:
    """2 行に折り返す分割位置（文字インデックス）を選ぶ。

    breaks（形態素境界）が与えられればその位置だけを候補にする（語の途中で割らない）。
    禁則処理も併用。breaks 内に妥当な位置が無ければ禁則のみで再探索する。
    """
    n = len(text)
    maxc = cfg.max_chars_per_line
    preferred = preferred or set()

    def allowed(i: int) -> bool:
        if not _breakable(text, i):
            return False
        return breaks is None or i in breaks

    if cfg.line_break == "greedy":
        for i in range(min(maxc, n - 1), 0, -1):
            if allowed(i) and (i in preferred or text[i - 1] in _BREAK_AFTER):
                return i
        for i in range(min(maxc, n - 1), 0, -1):
            if allowed(i):
                return i
        return _choose_split(text, cfg, None, preferred) if breaks is not None else min(maxc, n - 1)

    # balanced: 中央に近く、両行が maxc 以内を優先。境界直後・優先位置を加点。
    ideal = n / 2
    best_i = None
    best_score = None
    for i in range(1, n):
        if not allowed(i):
            continue
        if _vlen(text[:i]) > maxc or _vlen(text[i:]) > maxc:
            continue
        score = abs(i - ideal)
        if i in preferred:
            score -= 5
        elif text[i - 1] in _BREAK_AFTER:
            score -= 3
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    if best_i is not None:
        return best_i
    # 形態素境界で割れない → 禁則のみで再探索
    if breaks is not None:
        return _choose_split(text, cfg, None, preferred)
    # 禁則を満たす分割が maxc 内に無い → 禁則だけ満たす中央寄りの位置。
    for off in range(0, n):
        for i in (round(ideal) + off, round(ideal) - off):
            if _breakable(text, i):
                return i
    return max(1, min(n - 1, round(ideal)))


def _wrap_lines(text: str, cfg: SubtitleConfig, tokenizer: Tokenizer | None = None) -> list[str]:
    """cue テキストを最大 max_lines 行へ改行する。

    tokenizer があれば形態素境界のみで改行する（語の途中で割らない）。
    """
    if _vlen(text) <= cfg.max_chars_per_line or cfg.max_lines <= 1:
        return [text]
    breaks = preferred = None
    if tokenizer is not None:
        try:
            breaks = tokenizer.boundaries(text)
            preferred = tokenizer.preferred_breaks(text)
        except Exception:  # noqa: BLE001 - 解析失敗時は禁則のみ
            breaks = preferred = None
    idx = _choose_split(text, cfg, breaks, preferred)
    line1 = text[:idx].strip()
    line2 = text[idx:].strip()
    return [ln for ln in (line1, line2) if ln]


def _merge_tiny(raw: list[list], cfg: SubtitleConfig) -> list[list]:
    """極小 cue（min_cue_chars 未満）を、時間的に近い隣へ結合する。

    各要素は [start, end, text]。細切れの 1〜2 文字断片（相槌・言いよどみや
    Whisper の分割ゆらぎ）が単独字幕になるのを防ぐ。文字数上限を超える結合はしない。
    """
    if cfg.min_cue_chars <= 0:
        return raw
    rows = [list(r) for r in raw]
    stuck: set[int] = set()
    while len(rows) > 1:
        idx = next(
            (i for i, r in enumerate(rows)
             if _vlen(r[2]) < cfg.min_cue_chars and id(r) not in stuck),
            None,
        )
        if idx is None:
            break
        cur = rows[idx]

        def _same_speaker(a: list, b: list) -> bool:
            # 話者ラベルが両方あって異なるなら結合しない（話者境界を保持）
            return len(a) < 4 or len(b) < 4 or a[3] is None or b[3] is None or a[3] == b[3]

        prev_ok = (
            idx > 0
            and _vlen(rows[idx - 1][2]) + _vlen(cur[2]) <= cfg.max_chars_per_cue
            and _same_speaker(rows[idx - 1], cur)
        )
        next_ok = (
            idx + 1 < len(rows)
            and _vlen(cur[2]) + _vlen(rows[idx + 1][2]) <= cfg.max_chars_per_cue
            and _same_speaker(cur, rows[idx + 1])
        )
        if not prev_ok and not next_ok:
            stuck.add(id(cur))
            continue
        if prev_ok and next_ok:
            prev_gap = cur[0] - rows[idx - 1][1]
            next_gap = rows[idx + 1][0] - cur[1]
            choose_prev = prev_gap <= next_gap
        else:
            choose_prev = prev_ok
        if choose_prev:
            rows[idx - 1][1] = cur[1]
            rows[idx - 1][2] = rows[idx - 1][2] + cur[2]
        else:
            rows[idx + 1][0] = cur[0]
            rows[idx + 1][2] = cur[2] + rows[idx + 1][2]
        del rows[idx]
    return rows


def _fix_durations(cues: list[Cue], cfg: SubtitleConfig) -> None:
    """重なりをクランプし、最小表示秒・読み速度で表示時間を補正する。"""
    n = len(cues)
    for i, cue in enumerate(cues):
        next_start = cues[i + 1].start if i + 1 < n else None
        # 次 cue と重なるなら詰める
        if next_start is not None and cue.end > next_start - _MIN_GAP:
            cue.end = max(cue.start + 0.1, next_start - _MIN_GAP)
        # 必要表示秒 = max(最小秒, 文字数/最大cps)
        need = cfg.min_duration_s
        if cfg.max_cps > 0:
            need = max(need, _vlen(cue.text) / cfg.max_cps)
        if cue.duration < need:
            cap = (next_start - _MIN_GAP) if next_start is not None else cue.start + need
            cue.end = max(cue.end, min(cue.start + need, cap))
        if cue.end <= cue.start:
            cue.end = cue.start + 0.3


def build_cues(segments: list[Segment], cfg: SubtitleConfig | None = None) -> list[Cue]:
    """segment 列から整形済みの Cue 列を作る。"""
    cfg = cfg or SubtitleConfig()
    words = _collect_words(segments, cfg)
    groups = _group_words(words, cfg)

    # 1) グループ → [start, end, text, speaker]（テキスト後処理まで。改行はマージ後）
    rows: list[list] = []
    for group in groups:
        text = "".join(w.text for w in group).strip()
        text = apply_term_map(text, cfg.term_map)
        text = apply_punctuation_mode(text, cfg.punctuation_mode)
        text = text.strip()
        if not text:
            continue
        rows.append([group[0].start, group[-1].end, text, _majority_speaker(group)])

    # 2) 極小 cue を隣へ結合
    rows = _merge_tiny(rows, cfg)

    # 3) 改行して Cue 化（形態素解析があれば語境界で改行）
    tokenizer = get_tokenizer(cfg.morph)
    cues: list[Cue] = []
    for start, end, text, speaker in rows:
        lines = _wrap_lines(text, cfg, tokenizer)
        if not lines:
            continue
        cues.append(
            Cue(index=len(cues) + 1, start=start, end=end, lines=lines, speaker=speaker)
        )

    # 4) 表示時間の補正
    _fix_durations(cues, cfg)
    return cues


def wrap_text(text: str, cfg: SubtitleConfig | None = None) -> list[str]:
    """任意テキストを cfg に従って行に折り返す（LLM後補正の再整形などに使う）。"""
    cfg = cfg or SubtitleConfig()
    return _wrap_lines(text, cfg, get_tokenizer(cfg.morph))
