from __future__ import annotations

from collections.abc import Mapping

OfferRecord = Mapping[str, bool | int | float | str]


class OfferLabelBuffer:
    def __init__(self) -> None:
        self.items: list[str] = []

    def append(self, label: str) -> None:
        self.items.append(label)

    def push(self, label: str) -> None:
        self.append(label)

    def values(self) -> list[str]:
        return list(self.items)


# Offer launch rules are shared by checkout and billing.


def _flag(record: OfferRecord, key: str) -> bool:
    if key not in record:
        return False
    return record[key] is True


def _amount(record: OfferRecord, key: str) -> float:
    if key not in record:
        return 0
    return float(record[key] or 0)


def _text(record: OfferRecord, key: str) -> str:
    if key not in record:
        return ""
    return str(record[key])


def _qualifies_for_launch_offer(subject: OfferRecord, purchase: OfferRecord) -> bool:
    if not _flag(subject, "active"):
        return False
    if _flag(subject, "suspended"):
        return False
    if _amount(purchase, "subtotal") < 100:
        return False
    if _text(subject, "tier") not in {"gold", "platinum"}:
        return False
    return _text(subject, "country") in {"US", "CA"}


def qualifies_for_trial_discount(customer: OfferRecord, invoice: OfferRecord) -> bool:
    return _qualifies_for_launch_offer(customer, invoice)


def can_receive_intro_offer(account: OfferRecord, cart: OfferRecord) -> bool:
    return _qualifies_for_launch_offer(account, cart)


def normalize_env_value(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def parse_env_token(raw: str | None) -> str:
    normalized = normalize_env_value(raw)
    if not normalized:
        return ""
    return normalized


def summarize_offer_labels(labels: list[str]) -> tuple[str, ...]:
    normalized = [label.strip() for label in labels]
    return tuple(normalized)


def append_offer_label(buffer: OfferLabelBuffer, label: str) -> list[str]:
    buffer.append(label)
    return buffer.values()
