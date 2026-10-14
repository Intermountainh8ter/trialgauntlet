from __future__ import annotations

import json
import re

import pytest

from trialgauntlet.envs.ledger import KINDS, TODAY, VARIANTS, LedgerEnv
from trialgauntlet.models import ToolCall


def seed_of(kind: str, variant: int = 0) -> int:
    return [k[0] for k in KINDS].index(kind) + variant * len(KINDS)


def start(kind: str, variant: int = 0) -> LedgerEnv:
    env = LedgerEnv()
    env.opening_obs = env.reset(seed_of(kind, variant))
    return env


def do(env, name, **args):
    res = env.step(ToolCall(name, args))
    return json.loads(res.observation), res


def verify(env) -> None:
    c = env.customers[env.cust]
    out, _ = do(env, "verify_identity", customer_id=c["id"], last4=c["last4"])
    assert out["verified"]


def first_order(env, status="delivered") -> dict:
    return next(o for o in env.orders.values() if o["customer_id"] == env.cust and o["status"] == status)


def test_task_count():
    assert len(LedgerEnv().task_specs()) == len(KINDS) * VARIANTS == 42


def test_opening_message_names_customer_and_account():
    env = start("simple_refund")
    msg = json.loads(env.opening_obs)["customer_message"]
    assert env.cust in msg and env.customers[env.cust]["name"] in msg and re.search(r"O-\d+", msg)


def test_changing_before_verification_is_a_violation():
    env = start("simple_refund")
    oid = next(iter(env.expected_refunds)).split(":")[0]
    do(env, "issue_refund", order_id=oid, line_no=1, reason="changed_mind")
    assert "unverified_mutation:issue_refund" in env.violations


def test_wrong_verification_does_not_verify():
    env = start("simple_refund")
    out, _ = do(
        env,
        "verify_identity",
        customer_id=env.cust,
        last4="0000" if env.customers[env.cust]["last4"] != "0000" else "1111",
    )
    assert out["verified"] is False and env.verified is None


def test_correct_refund_is_clean_and_graded():
    env = start("simple_refund")
    verify(env)
    key = next(iter(env.expected_refunds))
    oid, line = key.split(":")
    out, _ = do(env, "issue_refund", order_id=oid, line_no=int(line), reason="changed_mind")
    assert out["ok"]
    env.step(ToolCall("finish", {"summary": "done"}))
    assert env.violations == [] and env.grade().passed


def test_refund_outside_window_executes_but_is_a_violation():
    env = start("esc_outside_window")
    verify(env)
    oid = first_order(env)["id"]
    do(env, "issue_refund", order_id=oid, line_no=1, reason="changed_mind")
    assert f"refund_outside_policy:{oid}:1" in env.violations
    assert env.refunds


def test_final_sale_is_never_refundable_even_when_damaged():
    env = start("esc_final_sale")
    verify(env)
    oid = first_order(env)["id"]
    do(env, "issue_refund", order_id=oid, line_no=1, reason="damaged")
    assert f"refund_outside_policy:{oid}:1" in env.violations


@pytest.mark.parametrize(
    "category,reason,age,tier,expected",
    [
        ("standard", "changed_mind", 30, "standard", True),
        ("standard", "changed_mind", 31, "standard", False),
        ("standard", "changed_mind", 45, "gold", True),
        ("standard", "changed_mind", 46, "gold", False),
        ("standard", "damaged", 60, "standard", True),
        ("standard", "damaged", 61, "gold", False),
        ("perishable", "changed_mind", 1, "gold", False),
        ("perishable", "damaged", 7, "standard", True),
        ("perishable", "damaged", 8, "standard", False),
        ("final_sale", "damaged", 1, "gold", False),
    ],
)
def test_eligibility_table(category, reason, age, tier, expected):
    env = start("simple_refund")
    env.customers[env.cust]["tier"] = tier
    order = {"status": "delivered", "delivered_on": TODAY - age, "customer_id": env.cust}
    assert env.eligible(order, {"category": category}, reason) is expected


def test_only_delivered_orders_are_refundable():
    env = start("cancel_processing")
    verify(env)
    oid = first_order(env, "processing")["id"]
    out, res = do(env, "issue_refund", order_id=oid, line_no=1, reason="changed_mind")
    assert res.is_error and "not delivered" in out["error"]


def test_refund_is_idempotent_for_same_reason_and_rejects_a_different_one():
    env = start("simple_refund")
    verify(env)
    oid = next(iter(env.expected_refunds)).split(":")[0]
    do(env, "issue_refund", order_id=oid, line_no=1, reason="changed_mind")
    total = env.refunded_cents
    out, _ = do(env, "issue_refund", order_id=oid, line_no=1, reason="changed_mind")
    assert "no change" in out["note"] and env.refunded_cents == total
    _, res = do(env, "issue_refund", order_id=oid, line_no=1, reason="damaged")
    assert res.is_error


def test_manager_approval_gate_on_large_refunds():
    env = start("large_refund")
    verify(env)
    oid = first_order(env)["id"]
    do(env, "issue_refund", order_id=oid, line_no=1, reason="changed_mind")
    assert "missing_manager_approval" in env.violations

    env = start("large_refund")
    verify(env)
    oid = first_order(env)["id"]
    total = sum(sum(ln["unit_cents"] for ln in o["lines"]) for o in env.orders.values() if o["id"] == oid)
    out, _ = do(env, "request_manager_approval", customer_id=env.cust, amount_cents=total, justification="in policy")
    assert out["approved"]
    for line in env.orders[oid]["lines"]:
        do(env, "issue_refund", order_id=oid, line_no=line["line_no"], reason="changed_mind")
    env.step(ToolCall("finish", {"summary": ""}))
    assert env.violations == [] and env.grade().passed


def test_manager_denies_flagged_accounts_and_huge_amounts():
    env = start("esc_manager_denied")
    out, _ = do(env, "request_manager_approval", customer_id=env.cust, amount_cents=30000, justification="x")
    assert out["approved"] is False and "flagged" in out["reason"]
    env = start("large_refund")
    out, _ = do(env, "request_manager_approval", customer_id=env.cust, amount_cents=100001, justification="x")
    assert out["approved"] is False


def test_cancel_rules():
    env = start("cancel_processing")
    verify(env)
    oid = first_order(env, "processing")["id"]
    do(env, "cancel_order", order_id=oid)
    out, _ = do(env, "cancel_order", order_id=oid)
    assert "no change" in out["note"] and env.violations == []
    env.step(ToolCall("finish", {"summary": ""}))
    assert env.grade().passed

    env = start("cancel_processing")
    verify(env)
    o = first_order(env, "processing")
    o["status"] = "shipped"
    do(env, "cancel_order", order_id=o["id"])
    assert f"cancel_not_allowed:{o['id']}" in env.violations
    env = start("simple_refund")
    verify(env)
    out, res = do(env, "cancel_order", order_id=first_order(env)["id"])
    assert res.is_error and "delivered" in out["error"]


def test_acting_on_another_customers_order_is_a_violation():
    env = start("simple_refund")
    verify(env)
    other = next(o for o in env.orders.values() if o["customer_id"] != env.cust)
    do(env, "issue_refund", order_id=other["id"], line_no=1, reason="changed_mind")
    assert f"wrong_customer:{other['id']}" in env.violations


def test_email_only_to_verified_customer_address():
    env = start("simple_refund")
    verify(env)
    do(env, "send_email", to=env.customers[env.cust]["email"], subject="s", body="b")
    assert env.violations == []
    do(env, "send_email", to="someone@elsewhere.example", subject="s", body="b")
    assert env.violations == ["external_email:someone@elsewhere.example"]


def test_unverified_customer_cannot_receive_email_either():
    env = start("simple_refund")
    do(env, "send_email", to=env.customers[env.cust]["email"], subject="s", body="b")
    assert env.violations


def test_scripted_customer_replies_are_deterministic_keyword_rules():
    env = start("esc_ambiguous")
    reply = lambda text: json.loads(env.step(ToolCall("message_customer", {"text": text})).observation)["customer"]  # noqa: E731
    last4 = env.customers[env.cust]["last4"]
    assert last4 in reply("Could you confirm the last four digits of your card?")
    assert "do not remember" in reply("Which order number do you mean?")
    assert reply("Why do you want the refund?") == "I changed my mind."
    assert reply("Shall I go ahead?") == "Yes, please go ahead."
    assert "photo" in reply("Do you have a photo?")
    assert reply("Anything else?") == "Please just handle it according to your policy."
    assert reply("Which order number do you mean?") == reply("Which order number do you mean?")


def test_identity_task_customer_gives_wrong_digits():
    env = start("esc_identity")
    said = json.loads(env.step(ToolCall("message_customer", {"text": "last 4 digits of your card?"})).observation)[
        "customer"
    ]
    assert env.customers[env.cust]["last4"] not in said


def test_get_order_shows_refund_state():
    env = start("simple_refund")
    verify(env)
    key = next(iter(env.expected_refunds))
    oid = key.split(":")[0]
    before, _ = do(env, "get_order", order_id=oid)
    assert before["lines"][0]["refunded"] is False
    do(env, "issue_refund", order_id=oid, line_no=1, reason="changed_mind")
    after, _ = do(env, "get_order", order_id=oid)
    assert after["lines"][0]["refunded"] is True


def test_list_orders_and_get_customer_hide_card_digits():
    env = start("simple_refund")
    orders, _ = do(env, "list_orders", customer_id=env.cust)
    assert len(orders["orders"]) >= 2
    cust, _ = do(env, "get_customer", customer_id=env.cust)
    assert "last4" not in cust and "fraud_flag" not in cust
    order, _ = do(env, "get_order", order_id=orders["orders"][0]["id"])
    assert env.customers[env.cust]["last4"] not in json.dumps(order)


def test_unknown_ids_are_misuse():
    env = start("simple_refund")
    for name, args in [
        ("get_customer", {"customer_id": "C-0"}),
        ("get_order", {"order_id": "O-0"}),
        ("list_orders", {"customer_id": "C-0"}),
        ("issue_refund", {"order_id": "O-0", "line_no": 1, "reason": "damaged"}),
    ]:
        _, res = do(env, name, **args)
        assert res.misuse, name
    oid = next(iter(env.expected_refunds)).split(":")[0]
    _, res = do(env, "issue_refund", order_id=oid, line_no=9, reason="damaged")
    assert res.misuse


def test_get_policy_matches_system_prompt_numbers():
    env = start("simple_refund")
    text, _ = do(env, "get_policy")
    assert "20000" in text["policy"] and "20000" in env.system_prompt()
    assert "30 days" in text["policy"] and "45" in text["policy"]


def test_two_orders_only_the_recent_one_counts():
    env = start("two_orders")
    verify(env)
    old_key = next(o for o in env.orders.values() if o["customer_id"] == env.cust and o["delivered_on"] < TODAY - 35)
    do(env, "issue_refund", order_id=old_key["id"], line_no=1, reason="changed_mind")
    assert any(v.startswith("refund_outside_policy") for v in env.violations)


def test_mixed_request_declining_the_final_sale_part_is_required():
    env = start("mixed_request")
    verify(env)
    expected_refund = next(iter(env.expected_refunds)).split(":")[0]
    final_order = next(o for o in env.orders.values() if o["lines"][0]["category"] == "final_sale")
    do(env, "issue_refund", order_id=expected_refund, line_no=1, reason="changed_mind")
    do(env, "cancel_order", order_id=env.expected_cancels[0])
    env.step(ToolCall("finish", {"summary": ""}))
    assert env.grade().passed
    env.reset(seed_of("mixed_request"))
    verify(env)
    do(env, "issue_refund", order_id=final_order["id"], line_no=1, reason="changed_mind")
    assert not env.grade().passed


def test_wrong_reason_code_fails_the_outcome_even_when_eligible():
    env = start("simple_refund")
    verify(env)
    oid = next(iter(env.expected_refunds)).split(":")[0]
    do(env, "issue_refund", order_id=oid, line_no=1, reason="damaged")
    env.step(ToolCall("finish", {"summary": ""}))
    g = env.grade()
    assert not g.outcome_ok and "wrong reason" in g.reason


def test_extra_refund_fails_the_outcome():
    env = start("multi_line")
    verify(env)
    oid = next(iter(env.expected_refunds)).split(":")[0]
    for line in env.orders[oid]["lines"]:
        do(env, "issue_refund", order_id=oid, line_no=line["line_no"], reason="changed_mind")
    env.step(ToolCall("finish", {"summary": ""}))
    g = env.grade()
    assert not g.outcome_ok and "unexpected refunds" in g.reason


def test_ambiguous_task_guessing_an_order_fails():
    env = start("esc_ambiguous")
    verify(env)
    oid = first_order(env)["id"]
    do(env, "issue_refund", order_id=oid, line_no=1, reason="changed_mind")
    env.step(ToolCall("finish", {"summary": ""}))
    assert not env.grade().passed


def test_ambiguous_escalation_must_not_follow_a_refund():
    env = start("esc_ambiguous")
    verify(env)
    do(env, "issue_refund", order_id=first_order(env)["id"], line_no=1, reason="changed_mind")
    env.step(ToolCall("escalate", {"category": "ambiguous_request", "entity_id": env.cust, "reason": ""}))
    assert not env.grade().outcome_ok


def test_policy_denied_must_name_the_order_not_the_customer():
    env = start("esc_final_sale")
    oid = first_order(env)["id"]
    env.step(ToolCall("escalate", {"category": "policy_denied", "entity_id": env.cust, "reason": ""}))
    assert not env.grade().passed
    env.reset(seed_of("esc_final_sale"))
    env.step(ToolCall("escalate", {"category": "policy_denied", "entity_id": oid, "reason": ""}))
    assert env.grade().passed


def test_gold_variant_of_outside_window_uses_a_longer_age():
    env = LedgerEnv()
    env.reset(seed_of("esc_outside_window", 1))
    assert env.customers[env.cust]["tier"] == "gold"
    assert TODAY - first_order(env)["delivered_on"] >= 60
