from pathlib import Path

from chipseeker.config_store import DEFAULT_CONFIG


def test_paid_api_access_ui_is_hidden_from_open_source_app():
    app_main = Path(__file__).resolve().parents[1] / "chipseeker" / "app_main.py"
    text = app_main.read_text(encoding="utf-8")

    assert "PUBLIC_CLOUD_ACCESS_UI_ENABLED = False" in text
    assert "Paid API Access" not in text
    assert "ChipSeeker Cloud Access" not in text
    assert "Paid Access Key" not in text


def test_open_source_default_deepseek_model_is_pro():
    app_main = Path(__file__).resolve().parents[1] / "chipseeker" / "app_main.py"
    example_config = Path(__file__).resolve().parents[1] / "config.example.json"

    assert DEFAULT_CONFIG["llm_model"] == "deepseek-v4-pro"
    assert '"llm_model": "deepseek-v4-pro"' in example_config.read_text(encoding="utf-8")
    assert 'else "deepseek-v4-pro"' in app_main.read_text(encoding="utf-8")


def test_full_content_package_is_local_only():
    app_main = Path(__file__).resolve().parents[1] / "chipseeker" / "app_main.py"
    text = app_main.read_text(encoding="utf-8")

    assert 'full_label = "Generate Full Package ZIP"' in text
    assert "Generate & Publish Full Package" not in text
    assert "Full packages stay local" in text
