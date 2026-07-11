from pathlib import Path


def test_paid_api_access_ui_is_hidden_from_open_source_app():
    app_main = Path(__file__).resolve().parents[1] / "chipseeker" / "app_main.py"
    text = app_main.read_text(encoding="utf-8")

    assert "PUBLIC_CLOUD_ACCESS_UI_ENABLED = False" in text
    assert "Paid API Access" not in text
    assert "ChipSeeker Cloud Access" not in text
    assert "Paid Access Key" not in text
