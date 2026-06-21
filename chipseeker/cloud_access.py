import base64
import json
from urllib.parse import urljoin

import requests


CLOUD_TOKEN_PREFIX = "chipseeker-cloud:"
DEFAULT_CLOUD_BASE_URL = "https://chipseeker.online"


def cloud_access_configured(email, access_code):
    return bool(str(email or "").strip() and str(access_code or "").strip())


# NOTE: The cloud token uses Base64 encoding for transport convenience only.
# It encodes the cloud service URL, email, and access code as a portable
# opaque string. Base64 is NOT encryption — the payload is reversible.
# Security relies on HTTPS transport and server-side access_code validation.
def build_cloud_token(base_url, email, access_code):
    payload = {
        "base_url": str(base_url or DEFAULT_CLOUD_BASE_URL).strip().rstrip("/"),
        "email": str(email or "").strip().lower(),
        "access_code": str(access_code or "").strip(),
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return CLOUD_TOKEN_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii")


def is_cloud_token(value):
    return str(value or "").startswith(CLOUD_TOKEN_PREFIX)


def parse_cloud_token(value):
    if not is_cloud_token(value):
        return {}
    encoded = str(value)[len(CLOUD_TOKEN_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    payload["base_url"] = str(payload.get("base_url") or DEFAULT_CLOUD_BASE_URL).strip().rstrip("/")
    payload["email"] = str(payload.get("email") or "").strip().lower()
    payload["access_code"] = str(payload.get("access_code") or "").strip()
    return payload


def _cloud_post(token, path, payload, timeout=120):
    auth = parse_cloud_token(token)
    if not auth:
        raise RuntimeError("ChipSeeker Cloud Access is not configured.")
    body = dict(payload)
    body.update({"email": auth["email"], "access_code": auth["access_code"]})
    url = urljoin(auth["base_url"] + "/", path.lstrip("/"))
    response = requests.post(url, json=body, timeout=timeout)
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(f"ChipSeeker Cloud Access request failed: {detail}")
    return response.json()


def cloud_embed(token, model, texts):
    data = _cloud_post(token, "/api/cloud/embeddings", {"model": model, "texts": list(texts)}, timeout=180)
    return data.get("embeddings", [])


def cloud_chat(token, prompt, model_name="deepseek-chat", temperature=0.3, system_prompt="You are a top-tier Cryo-CMOS & Quantum IC expert."):
    data = _cloud_post(
        token,
        "/api/cloud/chat",
        {
            "model": model_name,
            "system": system_prompt,
            "prompt": prompt,
            "temperature": temperature,
        },
        timeout=180,
    )
    return str(data.get("content", ""))
