import json
from collections.abc import Callable
from typing import TypeAlias

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonMap: TypeAlias = dict[str, JsonValue]

REVIEWABLE_STATUSES = {"new", "pending", "queued"}
CANCELLED_STATUS = "cancelled"


def _text_field(mapping: JsonMap, key: str) -> str:
    if key not in mapping:
        return ""
    value = mapping[key]
    if isinstance(value, str):
        return value
    return ""


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


def _parse_payload(raw: str) -> JsonMap:
    try:
        parsed = json.loads(raw or "{}")
    except ValueError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def parse_int_or_default(raw: JsonValue, default: int = 0) -> int:
    if not isinstance(raw, str):
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _book_score(item: JsonMap) -> float:
    quantity = _number_field(item, "quantity")
    price = _number_field(item, "price")
    region = _text_field(item, "region")
    if quantity <= 0 or price <= 10 or region not in {"us", "eu", "apac"}:
        return 0
    return price * quantity


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
    kind = _text_field(item, "kind")
    if kind not in ITEM_SCORERS:
        return 0
    return ITEM_SCORERS[kind](item)


def process_order(order: JsonMap) -> JsonMap:
    payload = _parse_payload(_text_field(order, "payload"))
    items = _list_path(order, ("data", "attributes", "items"))
    parsed_value = parse_int_or_default(_text_field(order, "value"))
    order_status = _text_field(order, "status")
    score = 0.0

    for item in items:
        if isinstance(item, dict):
            score += _score_item(item)

    if parsed_value > 100 and score > 20 and order_status in REVIEWABLE_STATUSES:
        status = "review"
    elif order_status == CANCELLED_STATUS:
        status = CANCELLED_STATUS
    elif score > 50:
        status = "approved"
    else:
        status = "manual"

    return {
        "id": _text_field(order, "id"),
        "payload_keys": sorted(str(key) for key in payload),
        "status": status,
        "score": score,
        "notes": [],
    }
