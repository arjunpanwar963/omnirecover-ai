"""
Tests for OmniRecoverEngine.process_record — the core guardrail logic.

Run with:
    pip install pytest
    pytest -v
"""

import pytest
from unittest.mock import MagicMock
from backend.engine import OmniRecoverEngine, MAX_DISCOUNT_PCT, MAX_ATTEMPTS


@pytest.fixture
def engine(monkeypatch):
    """
    Build an engine instance without needing a real Gemini API key or
    making real network calls.
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-not-real")
    eng = OmniRecoverEngine(data_path="unused.json")
    return eng


def make_record(**overrides):
    record = {
        "transaction_id": "txn_001",
        "customer_name": "Test Customer",
        "failure_type": "checkout_abandonment",
        "amount_inr": 1000,
        "user_intent": None,
        "attempt": 1,
    }
    record.update(overrides)
    return record


# --- 0. Missing API key should fail loudly, not fall back to a placeholder --

def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        OmniRecoverEngine(data_path="unused.json")


# --- 1. Opt-out hard stop (highest priority guardrail) ----------------------

def test_opt_out_stop_word_halts_immediately(engine):
    record = make_record(user_intent="STOP")
    result = engine.process_record(record)

    assert result["status"] == "ESCALATED_OPT_OUT"
    assert result["action_taken"] == "STOP"
    assert result["guardrail_triggered"] == "USER_OPT_OUT_DETECTED"
    assert result["money_recovered"] == 0


def test_do_not_disturb_halts_immediately(engine):
    record = make_record(user_intent="DO_NOT_DISTURB")
    result = engine.process_record(record)

    assert result["action_taken"] == "STOP"
    assert result["guardrail_triggered"] == "USER_OPT_OUT_DETECTED"


def test_opt_out_overrides_everything_even_first_attempt(engine):
    record = make_record(user_intent="STOP", attempt=1)
    result = engine.process_record(record)
    assert result["action_taken"] == "STOP"


# --- 2. Max attempt hard stop ------------------------------------------------
# NOTE: status name changed from "ESCALATED_OPT_OUT" to "ESCALATED_MAX_ATTEMPTS"
# now that the two guardrails are distinguishable.

def test_blocks_after_three_attempts(engine):
    record = make_record(attempt=MAX_ATTEMPTS)
    result = engine.process_record(record)

    assert result["status"] == "ESCALATED_MAX_ATTEMPTS"
    assert result["action_taken"] == "ESCALATE_HUMAN"
    assert result["guardrail_triggered"] == "MAX_ATTEMPTS_EXCEEDED"
    assert result["money_recovered"] == 0


def test_allows_attempt_two(engine, monkeypatch):
    # Attempt 2 should NOT be hard-stopped; it should reach the LLM/fallback path.
    record = make_record(attempt=2)
    monkeypatch.setattr(
        engine.model, "generate_content",
        MagicMock(side_effect=Exception("no real API in tests")),
    )
    result = engine.process_record(record)
    assert result["guardrail_triggered"] in ("NONE", "DISCOUNT_CAPPED")


# --- 3. Deterministic fallback when the LLM call fails ----------------------

def test_falls_back_when_gemini_call_fails(engine, monkeypatch):
    record = make_record(failure_type="checkout_abandonment", attempt=1)
    monkeypatch.setattr(
        engine.model, "generate_content",
        MagicMock(side_effect=Exception("simulated API outage")),
    )
    result = engine.process_record(record)

    assert result["status"] == "RECOVERED"
    assert result["action_taken"] == "SEND_PAYMENT_LINK"
    assert result["audit_reason"] == "Deterministic fallback applied."


def test_retries_once_before_falling_back(engine, monkeypatch):
    # First call fails, second call (the retry) succeeds.
    fake_llm_response = MagicMock()
    fake_llm_response.text = (
        '{"diagnosis": "recovered on retry", "action": "SEND_PAYMENT_LINK", "channel": "SMS", '
        '"recovery_message": "test", "suggested_discount_pct": 0.0, '
        '"promised_date": null, "attempt_used": 1, "reason_for_action": "test"}'
    )
    mock_call = MagicMock(side_effect=[Exception("transient error"), fake_llm_response])
    monkeypatch.setattr(engine.model, "generate_content", mock_call)
    monkeypatch.setattr("backend.engine.time.sleep", lambda *_: None)  # skip the real pause in tests

    record = make_record(attempt=1)
    result = engine.process_record(record)

    assert mock_call.call_count == 2
    assert result["audit_reason"] == "test"  # came from the LLM, not the fallback


# --- 3b. LLM-initiated STOP/ESCALATE_HUMAN gets its own status --------------

def test_llm_initiated_escalation_is_not_labeled_as_opt_out(engine, monkeypatch):
    """
    If the LLM itself decides to ESCALATE_HUMAN (not the hard-coded guardrail),
    the status should be "ESCALATED_BY_LLM", not "ESCALATED_OPT_OUT" — no
    opt-out actually happened here.
    """
    record = make_record(failure_type="b2b_invoice", attempt=1, user_intent=None)

    fake_llm_response = MagicMock()
    fake_llm_response.text = (
        '{"diagnosis": "very high risk account", "action": "ESCALATE_HUMAN", '
        '"channel": "NONE", "recovery_message": "", "suggested_discount_pct": 0.0, '
        '"promised_date": null, "attempt_used": 1, "reason_for_action": "flagged as high risk"}'
    )
    monkeypatch.setattr(
        engine.model, "generate_content",
        MagicMock(return_value=fake_llm_response),
    )

    result = engine.process_record(record)

    assert result["status"] == "ESCALATED_BY_LLM"
    assert result["status"] != "ESCALATED_OPT_OUT"
    assert result["action_taken"] == "ESCALATE_HUMAN"


# --- 4. Discount ceiling IS now enforced in code ----------------------------

def test_discount_over_cap_is_clamped(engine, monkeypatch):
    """
    Previously this was a documented gap (a 40% discount would pass straight
    through). Now the engine clamps it to MAX_DISCOUNT_PCT and flags it in
    the audit trail via guardrail_triggered.
    """
    record = make_record(failure_type="checkout_abandonment", amount_inr=1000, attempt=1)

    fake_llm_response = MagicMock()
    fake_llm_response.text = (
        '{"diagnosis": "test", "action": "SEND_PAYMENT_LINK", "channel": "SMS", '
        '"recovery_message": "test", "suggested_discount_pct": 40.0, '
        '"promised_date": null, "attempt_used": 1, "reason_for_action": "test"}'
    )
    monkeypatch.setattr(
        engine.model, "generate_content",
        MagicMock(return_value=fake_llm_response),
    )

    result = engine.process_record(record)

    expected_recovered = 1000 * (1 - MAX_DISCOUNT_PCT / 100)  # 950.0 at a 5% cap
    assert result["money_recovered"] == expected_recovered
    assert result["guardrail_triggered"] == "DISCOUNT_CAPPED"


def test_discount_within_cap_is_untouched(engine, monkeypatch):
    record = make_record(failure_type="checkout_abandonment", amount_inr=1000, attempt=1)

    fake_llm_response = MagicMock()
    fake_llm_response.text = (
        '{"diagnosis": "test", "action": "SEND_PAYMENT_LINK", "channel": "SMS", '
        '"recovery_message": "test", "suggested_discount_pct": 3.0, '
        '"promised_date": null, "attempt_used": 1, "reason_for_action": "test"}'
    )
    monkeypatch.setattr(
        engine.model, "generate_content",
        MagicMock(return_value=fake_llm_response),
    )

    result = engine.process_record(record)

    assert result["money_recovered"] == 970.0  # 1000 * (1 - 0.03), untouched
    assert result["guardrail_triggered"] == "NONE"