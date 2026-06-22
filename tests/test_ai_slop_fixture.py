# aislop-ignore-next-line ai-slop/python-hallucinated-import
from workflow_sample.ai_slop_fixture import (
    LabelBuffer,
    append_offer_label,
    can_receive_intro_offer,
    normalize_feature_flag,
    parse_rollout_switch,
    qualifies_for_trial_discount,
    summarize_offer_labels,
)


def test_trial_discount_candidate_is_truthy():
    customer = {
        "active": True,
        "suspended": False,
        "tier": "gold",
        "country": "US",
    }
    invoice = {"subtotal": 150}

    result = qualifies_for_trial_discount(customer, invoice)

    assert result


def test_parallel_offer_rule_matches_expected_result():
    account = {
        "active": True,
        "suspended": False,
        "tier": "platinum",
        "country": "CA",
    }
    cart = {"subtotal": 120}

    assert can_receive_intro_offer(account, cart) is True


def test_rollout_switch_helpers_parse_known_values():
    assert normalize_feature_flag(" enabled ") is True
    assert parse_rollout_switch("off", fallback=True) is False


def test_offer_label_helpers_return_labels():
    buffer = LabelBuffer()

    assert append_offer_label(buffer, "trial") == ["trial"]
    assert summarize_offer_labels(["trial", "vip"]) == ("trial", "vip")
