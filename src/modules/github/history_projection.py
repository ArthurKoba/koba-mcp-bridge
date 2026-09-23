from __future__ import annotations

from common.models import JsonObject, json_bool, json_int, json_object, json_str


def _as_object(item: object) -> JsonObject:
    try:
        return json_object(item)
    except ValueError:
        return {}


def _actor(item: object) -> JsonObject:
    data = _as_object(item)
    raw_id = data.get("id")
    return {
        "login": json_str(data.get("login")) or None,
        "id": json_int(raw_id) if raw_id is not None else None,
        "type": json_str(data.get("type")) or None,
    }


def git_identity(item: object, actor: object) -> JsonObject:
    data = _as_object(item)
    result: JsonObject = {
        "name": json_str(data.get("name")),
        "email": json_str(data.get("email")),
        "date": json_str(data.get("date")),
    }
    result.update(_actor(actor))
    return result


def verification(item: object, *, include_material: bool) -> JsonObject:
    data = _as_object(item)
    result: JsonObject = {
        "verified": json_bool(data.get("verified")),
        "reason": json_str(data.get("reason")),
        "verified_at": data.get("verified_at"),
        "signature_present": bool(data.get("signature")),
        "payload_present": bool(data.get("payload")),
    }
    if include_material:
        result["signature"] = data.get("signature")
        result["payload"] = data.get("payload")
    return result
