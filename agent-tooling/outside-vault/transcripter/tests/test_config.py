import pytest

from transcripter.config import Config, load_config


def test_defaults_apple_silicon():
    cfg = load_config()
    assert cfg.model == "turbo"
    assert cfg.language == "ja"
    assert cfg.device == "cpu"
    assert cfg.compute_type == "int8"
    assert cfg.formats == ["txt"]


def test_overrides_take_priority():
    cfg = load_config(overrides={"language": "en", "formats": ["json"]})
    assert cfg.language == "en"
    assert cfg.formats == ["json"]


def test_none_overrides_ignored():
    cfg = load_config(overrides={"language": None})
    assert cfg.language == "ja"


def test_toml_loading(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[defaults]\nlanguage = "en"\nformat = ["txt", "json"]\ndevice = "cpu"\n'
        '[logging]\nlevel = "debug"\n',
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert cfg.language == "en"
    assert cfg.formats == ["txt", "json"]
    assert cfg.log_level == "debug"


def test_cli_overrides_toml(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[defaults]\nlanguage = "en"\n', encoding="utf-8")
    cfg = load_config(str(p), overrides={"language": "fr"})
    assert cfg.language == "fr"


def test_invalid_format_rejected():
    with pytest.raises(ValueError):
        Config(formats=["docx"]).validate()


def test_subtitle_formats_accepted():
    # srt/vtt/ass はサポート対象
    Config(formats=["srt", "vtt", "ass"]).validate()


def test_invalid_device_rejected():
    with pytest.raises(ValueError):
        Config(device="mps").validate()


def test_default_pdf_backend():
    assert load_config().pdf_backend == "pymupdf4llm"


def test_pdf_backend_from_toml(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[pdf]\nbackend = "docling"\n', encoding="utf-8")
    assert load_config(str(p)).pdf_backend == "docling"


def test_invalid_pdf_backend_rejected():
    with pytest.raises(ValueError):
        Config(pdf_backend="marker").validate()


def test_missing_config_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.toml")
