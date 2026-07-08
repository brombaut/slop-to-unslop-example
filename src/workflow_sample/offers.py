from __future__ import annotations

from collections.abc import Mapping

OfferRecord = Mapping[str, bool | int | float | str]


class OfferLabelBuffer:
    def __init__(self) -> None:
        self.items: list[str] = []

    def __len__(self) -> int:
        return len(self.items)

    @property
    def length(self) -> int:
        return len(self.items)

    def append(self, label: str) -> None:
        self.items.append(label)

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


def _is_offer_eligible(record: OfferRecord, subtotal_source: OfferRecord) -> bool:
    if not _flag(record, "active"):
        return False
    if _flag(record, "suspended"):
        return False
    if _amount(subtotal_source, "subtotal") < 100:
        return False
    if _text(record, "tier") not in {"gold", "platinum"}:
        return False
    return _text(record, "country") in {"US", "CA"}


def qualifies_for_trial_discount(customer: OfferRecord, invoice: OfferRecord) -> bool:
    return _is_offer_eligible(customer, invoice)


def can_receive_intro_offer(account: OfferRecord, cart: OfferRecord) -> bool:
    return _is_offer_eligible(account, cart)


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


def has_offer_labels(buffer: OfferLabelBuffer) -> bool:
    return len(buffer) > 0


def append_offer_label(buffer: OfferLabelBuffer, label: str) -> list[str]:
    buffer.append(label)
    return buffer.values()
