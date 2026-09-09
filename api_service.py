from __future__ import annotations

import hmac
import json
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def require_api_key(headers: Mapping[str, str], expected: str | None) -> None:
    if not expected:
        raise PermissionError("UNAUTHORIZED: HME_API_KEY is not configured")
    candidate = _header_value(headers, "X-API-Key") or ""
    if not hmac.compare_digest(candidate, expected):
        raise PermissionError("UNAUTHORIZED: invalid API key")


def ok_response(data: Any, request_id: str | None = None) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None, "meta": _meta(request_id)}


def error_response(code: str, message: str, request_id: str | None = None) -> dict[str, Any]:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}, "meta": _meta(request_id)}


def list_aliases(client: Any) -> dict[str, Any]:
    return ok_response(client.list_aliases())


def create_alias(client: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    label = str(payload.get("label", "")).strip()
    if not label:
        raise ValueError("label is required")
    note = str(payload.get("note", ""))
    return ok_response(client.create_alias(label=label, note=note))


def session_status(source: Any) -> dict[str, Any]:
    if hasattr(source, "status"):
        return ok_response(source.status())
    return ok_response(source.check())


def refresh_session(source: Any) -> dict[str, Any]:
    if hasattr(source, "refresh_via_validate"):
        return ok_response(source.refresh_via_validate())
    return ok_response(source.check())


def browser_status(manager: Any) -> dict[str, Any]:
    """Expose only the browser agent's non-secret health snapshot."""
    path = Path(manager.state_dir) / "browser-agent.json"
    data: dict[str, Any] = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, json.JSONDecodeError):
        data = {}

    allowed = (
        "phase",
        "updatedAt",
        "lastImportAt",
        "sessionValid",
        "needsReauth",
        "region",
        "lastError",
    )
    result = {key: data[key] for key in allowed if key in data}
    try:
        updated_at = float(data.get("updatedAt") or 0)
    except (TypeError, ValueError):
        updated_at = 0
    result["configured"] = str(os.environ.get("HME_BROWSER_AGENT_ENABLED", "1")).lower() not in {"0", "false", "no"}
    result["running"] = bool(updated_at and time.time() - updated_at < 180)
    result["publicUrl"] = str(os.environ.get("HME_BROWSER_PUBLIC_URL", "") or "").strip()
    result["publicPort"] = str(os.environ.get("HME_BROWSER_WEB_PORT", "7900") or "7900").strip()
    if result.get("lastError") is None:
        result.pop("lastError", None)
    elif "lastError" in result:
        message = " ".join(str(result["lastError"]).split())
        api_key = str(os.environ.get("HME_API_KEY", "") or "")
        if api_key:
            message = message.replace(api_key, "[redacted]")
        message = re.sub(
            r"(?i)(x-api-key|authorization|cookie|password|api[_-]?key)\s*[:=]\s*[^,\s]+",
            r"\1=<redacted>",
            message,
        )
        result["lastError"] = message[:300]
    return ok_response(result)


def import_session(manager: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    curl_text = str(payload.get("curl_text", "")).strip()
    if not curl_text:
        raise ValueError("curl_text is required")
    from session_import import parse_import_text, save_imported_session

    config = parse_import_text(curl_text)
    save_imported_session(config, Path(manager.config_path), Path(manager.metadata_path))
    manager.reload()
    return ok_response({"imported": True, "region": _region_of(config)})


def _region_of(config: Mapping[str, Any]) -> str:
    from hme import region_for_host

    return region_for_host(str(config.get("host", "")))


def export_aliases_csv(client: Any) -> str:
    from hme import aliases_to_csv
    return aliases_to_csv(client.list_aliases())


def list_mail_folders(client: Any) -> dict[str, Any]:
    return ok_response(client.list_folders())


def list_mail_messages(client: Any, query: Mapping[str, Any]) -> dict[str, Any]:
    # Validate paging params before inbox_folder(), which hits the network.
    limit = _int_param(query, "limit", default=20, minimum=1, maximum=100)
    offset = _int_param(query, "offset", default=0, minimum=0, maximum=None)
    to = str(query.get("to") or "").strip()
    folder = str(query.get("folder") or "").strip()
    if not folder:
        folder = str(client.inbox_folder().get("guid") or "")
    if not folder:
        raise ValueError("folder is required (no inbox folder could be detected)")
    return ok_response(client.list_messages(folder, limit=limit, offset=offset, to=to or None))


def get_mail_message(client: Any, message_guid: str) -> dict[str, Any]:
    if not message_guid.strip():
        raise ValueError("message guid is required")
    return ok_response(client.get_message(message_guid))


def _int_param(query: Mapping[str, Any], name: str, default: int, minimum: int, maximum: int | None) -> int:
    raw = query.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def disable_alias(client: Any, anonymous_id: str) -> dict[str, Any]:
    return ok_response(client.deactivate_alias(anonymous_id))


def delete_alias(client: Any, anonymous_id: str) -> dict[str, Any]:
    return ok_response(client.delete_alias(anonymous_id))


def enable_alias(client: Any, anonymous_id: str) -> dict[str, Any]:
    return ok_response(client.activate_alias(anonymous_id))


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    value = headers.get(name)
    if value is not None:
        return str(value)
    lowered = name.lower()
    for key, candidate in headers.items():
        if str(key).lower() == lowered:
            return str(candidate)
    return None


def _meta(request_id: str | None) -> dict[str, str | None]:
    return {"service": "hme-manager", "version": "1", "requestId": request_id}
