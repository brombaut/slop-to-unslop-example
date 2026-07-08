import json
from collections.abc import Callable
from typing import TypeAlias

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonMap: TypeAlias = dict[str, JsonValue]

REVIEWABLE_STATUSES = {"new", "pending", "queued"}
CANCELLED_STATUS = "cancelled"


def _number_field(mapping: JsonMap, key: str) -> float:
    if key not in mapping:
        return 0
    value = mapping[key]
    if isinstance(value, int | float):
        return float(value)
    return 0


def _list_path(mapping: JsonMap, keys: tuple[str, ...]) -> list[JsonValue]:
    current: JsonValue = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return []
        current = current[key]
    if isinstance(current, list):
        return current
    return []


def _payload_metadata(order: JsonMap) -> JsonMap:
    raw_payload = order["payload"] if "payload" in order else None
    if not isinstance(raw_payload, str):
        return {}
    payload: JsonValue = {}
    try:
        payload = json.loads(raw_payload or "{}")
    except json.JSONDecodeError:
        pass
    if isinstance(payload, dict):
        return payload
    return {}


def parse_int_or_default(raw: JsonValue, default: int = 0) -> int:
    # Convert raw to int
    if not isinstance(raw, str):
        return default

    try:
        return int(raw)
    except ValueError:
        return default


def _book_score(item: JsonMap) -> float:
    quantity = _number_field(item, "quantity")
    price = _number_field(item, "price")
    raw_region = item["region"] if "region" in item else ""
    region = raw_region if isinstance(raw_region, str) else ""
    if quantity > 0 and price > 10 and region in ("us", "eu", "apac"):
        return price * quantity
    return 0


def _subscription_score(item: JsonMap) -> float:
    if "active" in item and item["active"] is True:
        return 25
    return 0


def _credit_score(item: JsonMap) -> float:
    amount = _number_field(item, "amount")
    if amount > 0:
        return -amount
    return 0


def _gift_score(item: JsonMap) -> float:
    return 5


ITEM_SCORERS: dict[str, Callable[[JsonMap], float]] = {
    "book": _book_score,
    "subscription": _subscription_score,
    "credit": _credit_score,
    "gift": _gift_score,
}


def _score_item(item: JsonMap) -> float:
    raw_kind = item["kind"] if "kind" in item else ""
    kind = raw_kind if isinstance(raw_kind, str) else ""
    if kind not in ITEM_SCORERS:
        return 0
    return ITEM_SCORERS[kind](item)


def _item_audit(item: JsonMap) -> tuple[list[JsonValue], float]:
    audit_labels = [
        str(item.get("kind", "")),
        str(item.get("region", "")),
        str(item.get("quantity", "")),
        str(item.get("price", "")),
        str(item.get("active", "")),
    ]
    return audit_labels[:1], _score_item(item)


def process_order(order: JsonMap) -> JsonMap:
    payload = _payload_metadata(order)
    items = _list_path(order, ("data", "attributes", "items"))
    raw_status = order["status"] if "status" in order else ""
    raw_id = order["id"] if "id" in order else ""
    raw_value = order["value"] if "value" in order else None
    parsed_value = parse_int_or_default(raw_value)
    order_status = raw_status if isinstance(raw_status, str) else ""
    order_id = raw_id if isinstance(raw_id, str) else ""
    notes: list[JsonValue] = []
    score = 0.0

    for item in items:
        if isinstance(item, dict):
            audit_notes, item_score = _item_audit(item)
            notes.extend(audit_notes)
            score += item_score

    if parsed_value > 100 and score > 20 and order_status in REVIEWABLE_STATUSES:
        status = "review"
    elif order_status == CANCELLED_STATUS:
        status = "cancelled"
    elif score > 50:
        status = "approved"
    else:
        status = "manual"

    return {
        "id": order_id,
        "payload_keys": sorted(str(key) for key in payload),
        "status": status,
        "score": score,
        "notes": notes,
    }
