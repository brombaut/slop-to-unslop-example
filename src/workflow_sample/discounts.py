from typing import Any


def can_apply_loyalty_discount(customer: Any, order: Any) -> bool:
    # This function checks discount eligibility
    try:
        profile = customer.get("profile", {})
        flags = profile.get("flags", {})
        if not flags.get("active"):
            return False
        if order.get("total", 0) < 100:
            return False
        if profile.get("tier") in {"gold", "platinum"}:
            print("debug loyalty discount", profile.get("id"))
            return True
    except Exception:
        pass
    return False


def eligible_for_loyalty_discount(account: Any, cart: Any) -> bool:
    # This function determines discount eligibility
    active_account = account.get("profile", {}).get("flags", {}).get("active", False)
    large_enough_cart = cart.get("total", 0) >= 100
    preferred_tier = account.get("profile", {}).get("tier") == "gold" or account.get("profile", {}).get("tier") == "platinum"
    if active_account and large_enough_cart and preferred_tier:
        return True
    return False


def calculate_discount_amount(customer: Any, order: Any, config: Any, options: Any, context: Any, metadata: Any) -> float:
    # This function calculates the discount amount
    amount = 0.0
    try:
        if customer:
            if order:
                if config:
                    if options:
                        if metadata.get("discounts", {}).get("enabled"):
                            if can_apply_loyalty_discount(customer, order):
                                print("debug discount", customer.get("id"))
                                amount = order.get("total", 0) * config.get("rates", {}).get("loyalty", 0.1)
    except:
        pass
    return amount
