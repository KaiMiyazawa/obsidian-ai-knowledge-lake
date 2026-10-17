"""字幕整形エンジン（reflow）の単体テスト。"""

import pytest

from transcripter.core.backend import Segment, Word
from transcripter.core.subtitle.morph import get_tokenizer
from transcripter.core.subtitle.reflow import SubtitleConfig, build_cues


def _seg(words, sid=0):
    return Segment(
        id=sid,
        start=words[0][0],
        end=words[-1][1],
        text="".join(w[2] for w in words),
        words=[Word(start=s, end=e, text=t) for s, e, t in words],
    )


def test_gap_split():
    # 1秒の無音（gap=1.0 >= 0.8）で 2 つの cue に割れる
    seg = _seg([
        (0.0, 0.5, "おはよう"),
        (0.5, 1.0, "ございます"),
        (2.0, 2.5, "今日は"),
        (2.5, 3.0, "いい天気"),
    ])
    cues = build_cues([seg], SubtitleConfig())
    assert len(cues) == 2
    assert cues[0].start == 0.0
    assert cues[1].lines[0].startswith("今日は")


def test_max_chars_per_cue_split():
    words = [(i * 0.3, i * 0.3 + 0.3, "あ") for i in range(40)]
    seg = _seg(words)
    cfg = SubtitleConfig(max_chars_per_cue=28, gap_split_s=99, max_duration_s=999)
    cues = build_cues([seg], cfg)
    assert len(cues) >= 2
    for c in cues:
        # 各 cue の総文字数は上限以内
        assert sum(len(ln) for ln in c.lines) <= 28


def test_sentence_punctuation_split():
    seg = _seg([
        (0.0, 0.4, "そうだ"),
        (0.4, 0.8, "ね。"),
        (0.9, 1.3, "行こう"),
    ])
    cfg = SubtitleConfig(split_on_punctuation=True, gap_split_s=99)
    cues = build_cues([seg], cfg)
    assert cues[0].text.endswith("。")
    assert len(cues) == 2


def test_line_wrap_two_lines():
    # 14字超は 2 行に折り返す
    seg = _seg([(0.0, 5.0, "これはとても長い一文なので二行に折り返す必要があります")])
    cfg = SubtitleConfig(max_chars_per_line=14, max_lines=2)
    cues = build_cues([seg], cfg)
    assert len(cues[0].lines) == 2
    for ln in cues[0].lines:
        assert len(ln) <= 14


def test_min_duration_extended():
    # 0.2秒の短い cue は最小表示秒まで延長される（次が無いので延長可）
    seg = _seg([(0.0, 0.2, "はい")])
    cfg = SubtitleConfig(min_duration_s=1.2)
    cues = build_cues([seg], cfg)
    assert cues[0].duration >= 1.2 - 1e-6


def test_no_overlap():
    seg = _seg([
        (0.0, 0.2, "あ"),
        (0.3, 0.5, "い"),
    ])
    cfg = SubtitleConfig(min_duration_s=2.0, gap_split_s=0.05)  # 強制的に伸ばしたい状況
    cues = build_cues([seg], cfg)
    for a, b in zip(cues, cues[1:]):
        assert a.end <= b.start


def test_fallback_without_words():
    # words 無し（segment 単位）でもフォールバックで cue を作る
    seg = Segment(id=0, start=0.0, end=2.0, text="ワード時刻なしのフォールバック")
    cues = build_cues([seg], SubtitleConfig())
    assert len(cues) == 1
    assert "フォールバック" in cues[0].text


def test_term_map_applied():
    seg = _seg([(0.0, 1.0, "引き地"), (1.0, 2.0, "です")])
    cfg = SubtitleConfig(term_map=[("引き地", "引地")])
    cues = build_cues([seg], cfg)
    assert "引地" in cues[0].text
    assert "引き地" not in cues[0].text


def test_line_break_kinsoku_no_small_kana_at_line_head():
    # 形態素解析なしでも、行頭に小書き仮名（っ/ょ 等）を置かない（禁則）
    seg = _seg([(0.0, 5.0, "ちょっとまってしゅっぱつしんこうだよきっとね")])
    cfg = SubtitleConfig(max_chars_per_line=10, max_lines=2, morph="off")
    cues = build_cues([seg], cfg)
    for c in cues:
        for ln in c.lines:
            assert ln[0] not in "ぁぃぅぇぉっゃゅょ"


def test_morph_line_break_keeps_words_intact():
    if get_tokenizer("auto") is None:
        pytest.skip("形態素解析ライブラリ未導入（--extra morph）")
    # 「できます」を「で|きます」のように語の途中で割らない
    seg = _seg([(0.0, 5.0, "多分いろんなお買い物できますよ的なことなのかな")])
    cfg = SubtitleConfig(max_chars_per_line=14, max_lines=2, morph="auto")
    cues = build_cues([seg], cfg)
    joined_lines = [ln for c in cues for ln in c.lines]
    # どの行も「できます」を分断していない
    assert any("できます" in ln for ln in joined_lines)
    for ln in joined_lines:
        assert ln[0] not in "ぁぃぅぇぉっゃゅょ"


def test_tiny_cue_merged_to_nearer_neighbor():
    # 「ま」は直前(gap0.04)に近く、次(gap2.3)より前へ結合される
    seg = _seg([
        (0.0, 0.5, "こんにちは"),
        (16.0, 16.41, "です"),
        (16.45, 17.65, "ま"),      # 極小・前と gap0.04
        (19.95, 21.0, "だ行こう"),  # 次・gap2.3
    ])
    cfg = SubtitleConfig(min_cue_chars=3, gap_split_s=0.8, max_duration_s=999)
    cues = build_cues([seg], cfg)
    # 「ま」単独 cue が消え、直前に結合される
    assert all(sum(len(ln) for ln in c.lines) >= 3 or c is cues[-1] for c in cues)
    joined = "".join(c.text for c in cues)
    assert "ま" in joined
    # 「ま」だけの cue は存在しない
    assert not any(c.text == "ま" for c in cues)


def test_strip_fillers():
    seg = _seg([
        (0.0, 0.3, "えー"),
        (0.3, 0.8, "こんにちは"),
    ])
    cfg = SubtitleConfig(strip_fillers=True)
    cues = build_cues([seg], cfg)
    assert "えー" not in cues[0].text
    assert "こんにちは" in cues[0].text
