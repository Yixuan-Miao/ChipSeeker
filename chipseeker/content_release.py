import os
from dataclasses import dataclass
from typing import Any, Dict
from urllib.parse import quote

import requests


DEFAULT_RELEASE_TAG = "content-latest"
DEFAULT_UPDATE_ASSET = "ChipSeeker_ContentUpdate_latest.zip"
DEFAULT_FULL_ASSET = "ChipSeeker_ContentPack_latest.zip"


class ContentReleaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContentReleaseConfig:
    enabled: bool
    repo: str
    tag: str
    token: str
    update_asset_name: str
    full_asset_name: str


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def load_content_release_config(app_config: Dict[str, Any]) -> ContentReleaseConfig:
    """Load private release settings from env first, then local config.

    These values are intentionally not part of config.example.json. Normal open-source
    users should not see the internal publisher unless the owner explicitly enables it
    on their own machine.
    """
    enabled = _truthy(os.environ.get("CHIPSEEKER_CONTENT_RELEASE_ENABLED", app_config.get("content_release_enabled")))
    repo = os.environ.get("CHIPSEEKER_CONTENT_RELEASE_REPO") or str(app_config.get("content_release_repo", "")).strip()
    tag = os.environ.get("CHIPSEEKER_CONTENT_RELEASE_TAG") or str(app_config.get("content_release_tag", DEFAULT_RELEASE_TAG)).strip()
    token = os.environ.get("CHIPSEEKER_CONTENT_RELEASE_TOKEN") or str(app_config.get("content_release_token", "")).strip()
    update_asset = (
        os.environ.get("CHIPSEEKER_CONTENT_RELEASE_UPDATE_ASSET")
        or str(app_config.get("content_release_update_asset_name", "")).strip()
        or str(app_config.get("content_release_asset_name", "")).strip()
        or DEFAULT_UPDATE_ASSET
    )
    full_asset = (
        os.environ.get("CHIPSEEKER_CONTENT_RELEASE_FULL_ASSET")
        or str(app_config.get("content_release_full_asset_name", "")).strip()
        or DEFAULT_FULL_ASSET
    )
    return ContentReleaseConfig(
        enabled=enabled,
        repo=repo,
        tag=tag or DEFAULT_RELEASE_TAG,
        token=token,
        update_asset_name=update_asset,
        full_asset_name=full_asset,
    )


def content_release_configured(config: ContentReleaseConfig) -> bool:
    return bool(config.enabled and config.repo and config.tag and config.token)


def content_pack_publish_enabled(config: ContentReleaseConfig, pack_kind: str) -> bool:
    """Only incremental update packs are small enough for online publishing."""
    return str(pack_kind or "").strip().lower() == "update" and content_release_configured(config)


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ChipSeeker-ContentPublisher",
    }


def _request(method: str, url: str, token: str, **kwargs: Any) -> requests.Response:
    headers = _headers(token)
    headers.update(kwargs.pop("headers", {}) or {})
    response = requests.request(method, url, headers=headers, timeout=120, **kwargs)
    if response.status_code >= 400:
        detail = response.text[:500].replace(config_token_hint(token), "***")
        raise ContentReleaseError(f"GitHub release request failed ({response.status_code}): {detail}")
    return response


def config_token_hint(token: str) -> str:
    return token[-8:] if len(token) >= 8 else token


def _repo_parts(repo: str) -> tuple[str, str]:
    parts = repo.strip().split("/")
    if len(parts) != 2 or not all(parts):
        raise ContentReleaseError("content_release_repo must use owner/repo format.")
    return parts[0], parts[1]


def _get_or_create_release(config: ContentReleaseConfig) -> Dict[str, Any]:
    owner, repo = _repo_parts(config.repo)
    api_root = f"https://api.github.com/repos/{owner}/{repo}"
    tag_url = f"{api_root}/releases/tags/{quote(config.tag, safe='')}"
    response = requests.get(tag_url, headers=_headers(config.token), timeout=60)
    if response.status_code == 200:
        return response.json()
    if response.status_code != 404:
        detail = response.text[:500].replace(config_token_hint(config.token), "***")
        raise ContentReleaseError(f"GitHub release lookup failed ({response.status_code}): {detail}")

    payload = {
        "tag_name": config.tag,
        "name": "ChipSeeker private content latest",
        "body": "Private ChipSeeker content pack asset. Do not publish this release publicly.",
        "draft": False,
        "prerelease": False,
    }
    return _request("POST", f"{api_root}/releases", config.token, json=payload).json()


def publish_content_pack_to_release(zip_path: str, config: ContentReleaseConfig, asset_name: str | None = None) -> Dict[str, Any]:
    if not content_release_configured(config):
        raise ContentReleaseError("Private content release is not configured on this machine.")
    if not os.path.exists(zip_path):
        raise ContentReleaseError(f"Content pack not found: {zip_path}")

    release = _get_or_create_release(config)
    final_asset_name = asset_name or os.path.basename(zip_path)
    for asset in release.get("assets", []) or []:
        if asset.get("name") == final_asset_name:
            _request("DELETE", asset["url"], config.token)
            break

    upload_url = str(release.get("upload_url", "")).split("{", 1)[0]
    if not upload_url:
        raise ContentReleaseError("GitHub release upload URL was missing.")

    with open(zip_path, "rb") as handle:
        response = _request(
            "POST",
            f"{upload_url}?name={quote(final_asset_name)}",
            config.token,
            headers={"Content-Type": "application/zip"},
            data=handle,
        )
    uploaded = response.json()
    return {
        "release_url": release.get("html_url", ""),
        "asset_name": uploaded.get("name", final_asset_name),
        "asset_url": uploaded.get("browser_download_url", ""),
        "size_bytes": uploaded.get("size", os.path.getsize(zip_path)),
        "tag": config.tag,
        "repo": config.repo,
    }
