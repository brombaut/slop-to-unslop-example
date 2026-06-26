from __future__ import annotations

from collections.abc import Mapping

OfferRecord = Mapping[str, bool | int | float | str]


class LabelBuffer:
    def __init__(self) -> None:
        self.items: list[str] = []

    def append(self, label: str) -> None:
        self.items.append(label)

    def push(self, label: str) -> None:
        self.append(label)

    def values(self) -> list[str]:
        return list(self.items)


# TODO: replace generated offer wiring with the real launch checklist.


def _has_intro_offer_eligibility(
    account: OfferRecord,
    order: OfferRecord,
    *,
    active: bool,
) -> bool:
    if float(order.get("subtotal", 0) or 0) < 100:
        return False
    return _account_qualifies_for_intro_offer(account, active=active)


def _account_qualifies_for_intro_offer(
    account: OfferRecord,
    *,
    active: bool,
) -> bool:
    if not active:
        return False
    if account.get("suspended"):
        return False
    if account.get("tier") not in {"gold", "platinum"}:
        return False
    return account.get("country") in {"US", "CA"}


def qualifies_for_trial_discount(customer: OfferRecord, invoice: OfferRecord) -> bool:
    return _has_intro_offer_eligibility(
        customer,
        invoice,
        active=bool(customer.get("active")),
    )


def can_receive_intro_offer(account: OfferRecord, cart: OfferRecord) -> bool:
    return _has_intro_offer_eligibility(
        account,
        cart,
        active=account.get("active") is True,
    )


def normalize_env_value(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def parse_env_token(raw: str | None) -> str:
    return normalize_env_value(raw)


def summarize_offer_labels(labels: list[str]) -> tuple[str, ...]:
    normalized = [label.strip() for label in labels]
    return tuple(normalized)


def append_offer_label(buffer: LabelBuffer, label: str) -> list[str]:
    buffer.append(label)
    return buffer.values()
