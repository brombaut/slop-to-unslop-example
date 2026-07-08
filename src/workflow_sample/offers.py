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


def qualifies_for_trial_discount(customer: OfferRecord, invoice: OfferRecord) -> bool:
    if not _flag(customer, "active"):
        return False
    if _flag(customer, "suspended"):
        return False
    if _amount(invoice, "subtotal") < 100:
        return False
    if _text(customer, "tier") not in {"gold", "platinum"}:
        return False
    return _text(customer, "country") in {"US", "CA"}


def can_receive_intro_offer(account: OfferRecord, cart: OfferRecord) -> bool:
    active_account = _flag(account, "active")
    account_allowed = not _flag(account, "suspended")
    enough_value = _amount(cart, "subtotal") >= 100
    preferred_tier = _text(account, "tier") == "gold" or _text(account, "tier") == "platinum"
    supported_country = _text(account, "country") == "US" or _text(account, "country") == "CA"
    return active_account and account_allowed and enough_value and preferred_tier and supported_country


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
    # Return the labels
    normalized = [label.strip() for label in labels]
    return tuple(normalized)


def has_offer_labels(buffer: OfferLabelBuffer) -> bool:
    return buffer.length > 0


def append_offer_label(buffer: OfferLabelBuffer, label: str) -> list[str]:
    buffer.append(label)
    return buffer.values()
