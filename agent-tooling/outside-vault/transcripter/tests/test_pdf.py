import pytest

from transcripter.core.pdf import PDF_EXTS
from transcripter.core.pdf.converter import PdfOutcome, convert_pdf, make_backend
from transcripter.errors import PdfConversionError
from transcripter.output.markdown_writer import write_markdown


class _FakeBackend:
    """テスト用のダミーバックエンド。"""

    name = "fake"

    def __init__(self, md="# Title\n\n|a|b|\n", fail=False):
        self._md = md
        self._fail = fail

    def convert(self, pdf_path):
        if self._fail:
            raise PdfConversionError("boom")
        return self._md


def test_pdf_exts():
    assert PDF_EXTS == {".pdf"}


def test_make_backend_default():
    b = make_backend("pymupdf4llm")
    assert b.name == "pymupdf4llm"


def test_make_backend_invalid():
    with pytest.raises(PdfConversionError):
        make_backend("unknown")


def test_write_markdown(tmp_path):
    out = write_markdown("# Hello", tmp_path / "doc.pdf", tmp_path / "out")
    assert out is not None
    assert out.name == "doc.md"
    assert out.read_text(encoding="utf-8") == "# Hello\n"


def test_write_markdown_skips_existing(tmp_path):
    (tmp_path / "doc.md").write_text("既存", encoding="utf-8")
    out = write_markdown("# New", tmp_path / "doc.pdf", tmp_path, overwrite=False)
    assert out is None
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == "既存"


def test_write_markdown_overwrite(tmp_path):
    (tmp_path / "doc.md").write_text("既存", encoding="utf-8")
    out = write_markdown("# New", tmp_path / "doc.pdf", tmp_path, overwrite=True)
    assert out is not None
    assert "New" in out.read_text(encoding="utf-8")


def test_convert_pdf_success(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.touch()
    outcome = convert_pdf(pdf, _FakeBackend(), tmp_path / "out")
    assert isinstance(outcome, PdfOutcome)
    assert outcome.ok
    assert outcome.output.name == "doc.md"
    assert outcome.output.read_text(encoding="utf-8").startswith("# Title")


def test_convert_pdf_failure_is_captured(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.touch()
    outcome = convert_pdf(pdf, _FakeBackend(fail=True), tmp_path / "out")
    assert not outcome.ok
    assert outcome.output is None
    assert "boom" in outcome.error


def test_normalize_pdf_text_fixes_radical_lookalikes():
    from transcripter.output.markdown_writer import normalize_pdf_text

    assert normalize_pdf_text("お前も⽇本株") == "お前も日本株"
    assert normalize_pdf_text("中⻑期の⾼騰株") == "中長期の高騰株"
    assert normalize_pdf_text("シン‧フジコ") == "シン・フジコ"
