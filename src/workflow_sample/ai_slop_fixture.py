from __future__ import annotations

from collections.abc import Mapping

OfferRecord = Mapping[str, bool | int | float | str]


class LabelBuffer:
    def __init__(self) -> None:
        self.items: list[str] = []

    def push(self, label: str) -> None:
        self.items.append(label)

    def values(self) -> list[str]:
        return list(self.items)


# TODO: replace generated offer wiring with the real launch checklist.


def qualifies_for_trial_discount(customer: OfferRecord, invoice: OfferRecord) -> bool:
    if not customer.get("active"):
        return False
    if customer.get("suspended"):
        return False
    if float(invoice.get("subtotal", 0) or 0) < 100:
        return False
    if customer.get("tier") not in {"gold", "platinum"}:
        return False
    return customer.get("country") in {"US", "CA"}


def can_receive_intro_offer(account: OfferRecord, cart: OfferRecord) -> bool:
    active_account = account.get("active") is True
    account_allowed = not account.get("suspended", False)
    enough_value = float(cart.get("subtotal", 0) or 0) >= 100
    preferred_tier = account.get("tier") == "gold" or account.get("tier") == "platinum"
    supported_country = account.get("country") == "US" or account.get("country") == "CA"
    return active_account and account_allowed and enough_value and preferred_tier and supported_country


def normalize_feature_flag(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "enabled", "on"}:
        return True
    if normalized in {"0", "false", "no", "disabled", "off"}:
        return False
    return default


def parse_rollout_switch(raw: str | None, fallback: bool = False) -> bool:
    if raw is None:
        return fallback
    cleaned = raw.strip().lower()
    enabled_values = {"1", "true", "yes", "enabled", "on"}
    disabled_values = {"0", "false", "no", "disabled", "off"}
    if cleaned in enabled_values:
        return True
    if cleaned in disabled_values:
        return False
    return fallback


def summarize_offer_labels(labels: list[str]) -> tuple[str, ...]:
    # Return the labels
    normalized = [label.strip() for label in labels]
    return tuple(normalized)


def append_offer_label(buffer: LabelBuffer, label: str) -> list[str]:
    buffer.push(label)
    return buffer.values()
