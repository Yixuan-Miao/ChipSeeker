from contextlib import nullcontext

from chipseeker import app_main
from chipseeker.content_release import ContentReleaseConfig, content_pack_publish_enabled


def _configured_release():
    return ContentReleaseConfig(
        enabled=True,
        repo="owner/private-content",
        tag="content-latest",
        token="secret-token",
        update_asset_name="ChipSeeker_ContentUpdate_latest.zip",
        full_asset_name="ChipSeeker_ContentPack_latest.zip",
    )


def test_only_incremental_content_pack_can_publish():
    config = _configured_release()

    assert content_pack_publish_enabled(config, "update") is True
    assert content_pack_publish_enabled(config, "full") is False


def test_incremental_content_pack_still_requires_release_configuration():
    config = _configured_release()
    disabled = ContentReleaseConfig(**{**config.__dict__, "enabled": False})

    assert content_pack_publish_enabled(disabled, "update") is False


def _prepare_content_pack_ui(monkeypatch):
    monkeypatch.setattr(app_main, "load_app_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(app_main, "_content_pack_cache_block_reason", lambda _config: "")
    monkeypatch.setattr(app_main, "load_json", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(app_main.st, "spinner", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(app_main.st, "success", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_main.st, "error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_main, "_record_update_event_safely", lambda *_args, **_kwargs: None)


def test_full_content_pack_builds_locally_without_publish(monkeypatch):
    _prepare_content_pack_ui(monkeypatch)
    calls = {}

    def build_full(*_args, **kwargs):
        calls["build"] = kwargs
        return {"zip_path": "exports/ChipSeeker_ContentPack_20260721_120000.zip", "paper_count": 42}

    monkeypatch.setattr(app_main, "build_content_pack", build_full)
    monkeypatch.setattr(
        app_main,
        "publish_content_pack_to_release",
        lambda *_args, **_kwargs: calls.setdefault("publish", True),
    )
    monkeypatch.setattr(
        app_main,
        "refresh_content_pack_baseline",
        lambda *_args, **_kwargs: calls.setdefault("refresh", True),
    )

    app_main._build_and_publish_content_pack("full", _configured_release())

    assert calls["build"]["pack_name"] is None
    assert calls["build"]["save_state"] is True
    assert "publish" not in calls
    assert "refresh" not in calls


def test_latest_update_still_publishes_and_refreshes_baseline(monkeypatch):
    _prepare_content_pack_ui(monkeypatch)
    calls = {}

    def build_update(*_args, **kwargs):
        calls["build"] = kwargs
        return {
            "zip_path": "exports/ChipSeeker_ContentUpdate_latest.zip",
            "paper_count": 42,
        }

    monkeypatch.setattr(app_main, "build_content_update_pack", build_update)

    def publish(zip_path, _config, asset_name=None):
        calls["publish"] = (zip_path, asset_name)
        return {
            "asset_name": asset_name,
            "repo": "owner/private-content",
            "tag": "content-latest",
            "size_bytes": 1024,
        }

    monkeypatch.setattr(app_main, "publish_content_pack_to_release", publish)
    monkeypatch.setattr(
        app_main,
        "refresh_content_pack_baseline",
        lambda *_args, **kwargs: calls.setdefault("refresh", kwargs),
    )

    app_main._build_and_publish_content_pack("update", _configured_release())

    assert calls["build"]["save_state"] is False
    assert calls["publish"][1] == "ChipSeeker_ContentUpdate_latest.zip"
    assert calls["refresh"]["baseline_kind"] == "update"
