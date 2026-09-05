import json
import logging
import os
import time
from typing import Dict, Any, List

from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()  # loads GOOGLE_API_KEY from a local .env file, if present

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("omnirecover")

MAX_DISCOUNT_PCT = 5.0
MAX_ATTEMPTS = 3


class OmniRecoverEngine:
    def __init__(self, data_path: str = "data/dataset.json"):
        self.data_path = data_path

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY environment variable is not set. "
                "Create a .env file with GOOGLE_API_KEY=your_key_here "
                "(and make sure .env is in .gitignore) — never hardcode a real key in this file."
            )

        genai.configure(api_key=api_key)

        # Force JSON output directly at the model level
        self.model = genai.GenerativeModel(
            'gemini-1.5-flash',
            generation_config={"response_mime_type": "application/json"}
        )

    def load_dataset(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.data_path):
            raise FileNotFoundError(f"Dataset file not found at {self.data_path}")
        with open(self.data_path, 'r') as f:
            return json.load(f)

    def generate_agent_prompt(self, record: dict) -> str:
        failure_map = {
            "subscription_mandate": "MANDATE_REVOKED",
            "checkout_abandonment": "CART_ABANDONED",
            "b2b_invoice": "INVOICE_OVERDUE"
        }
        f_type = failure_map.get(record.get("failure_type"), "UPI_FAILED")
        opt_out = str(record.get("user_intent") in ["STOP", "DO_NOT_DISTURB"])
        attempt = record.get("attempt", 1)  # FIX: use the real attempt number, not a hardcoded 1

        return f"""
        You are OmniRecover AI, a zero-trust revenue recovery agent for Razorpay merchants.

        **INPUT DATA:**
        - Customer ID: {record.get('transaction_id')}
        - Failure Type: {f_type}
        - Attempt Number: {attempt}
        - Previous Channels Used: NONE
        - Customer Opt-Out Status: {opt_out}
        - Amount: ₹{record.get('amount_inr')}

        **NON-NEGOTIABLE RULES (Must strictly follow):**
        1. If `opt_out` is True -> `action: "STOP"`, reason: "Customer opted out".
        2. If `attempt` >= {MAX_ATTEMPTS} -> `action: "ESCALATE_HUMAN"`, reason: "Max retries exceeded".
        3. Discount ONLY allowed for `CART_ABANDONED`. Max discount = {MAX_DISCOUNT_PCT}%.
        4. Map failure to best channel:
           - MANDATE_REVOKED / UPI_FAILED -> WHATSAPP
           - INVOICE_OVERDUE -> EMAIL
           - CART_ABANDONED -> PAYMENT_LINK or SMS
           - CARD_EXPIRED -> PAYMENT_LINK

        **OUTPUT FORMAT:**
        Return a valid JSON object matching the exact keys below:
        {{
          "diagnosis": "Root cause string",
          "action": "STOP | RETRY_NOW | SEND_PAYMENT_LINK | SEND_REMINDER | ESCALATE_HUMAN",
          "channel": "WHATSAPP | SMS | EMAIL | PAYMENT_LINK | NONE",
          "recovery_message": "String message",
          "suggested_discount_pct": 0.0,
          "promised_date": "YYYY-MM-DD or null",
          "attempt_used": {attempt},
          "reason_for_action": "String explanation"
        }}
        """

    def _deterministic_fallback(self, record: dict) -> dict:
        """Failsafe if the API key is missing, rate limited, or the call fails."""
        opt_out = record.get("user_intent") in ["STOP", "DO_NOT_DISTURB"]
        is_abandoned = record.get("failure_type") == "checkout_abandonment"

        agent_decision = {
            "diagnosis": "Fallback: Customer opted out." if opt_out else f"Fallback: {record.get('failure_type')}",
            "action": "STOP" if opt_out else "SEND_PAYMENT_LINK",
            "channel": "NONE" if opt_out else ("PAYMENT_LINK" if is_abandoned else "WHATSAPP"),
            "recovery_message": "Action halted." if opt_out else f"Hi, complete your payment of ₹{record.get('amount_inr')}.",
            "suggested_discount_pct": MAX_DISCOUNT_PCT if (is_abandoned and not opt_out) else 0.0,
            "promised_date": None,
            "attempt_used": record.get("attempt", 1),
            "reason_for_action": "Deterministic fallback applied."
        }
        return agent_decision

    def _call_llm_with_retry(self, formatted_prompt: str, record: dict, retries: int = 1) -> dict:
        """
        Calls Gemini, retrying once on transient failure before giving up.
        Falls back to the deterministic path if all attempts fail.
        """
        last_error = None
        for attempt_no in range(retries + 1):
            try:
                response = self.model.generate_content(
                    f"{formatted_prompt}\n\nAnalyze this failure and return the JSON: {json.dumps(record)}"
                )
                return json.loads(response.text)
            except Exception as e:
                last_error = e
                logger.warning("Gemini API call failed (attempt %d/%d): %s", attempt_no + 1, retries + 1, e)
                if attempt_no < retries:
                    time.sleep(1)  # brief pause before retrying

        logger.error("Gemini API failed after %d attempt(s): %s — using deterministic fallback.", retries + 1, last_error)
        return self._deterministic_fallback(record)

    def process_record(self, record: dict) -> dict:
        # PART 1: HARD SAFETY CHECKS (these never touch the LLM)
        opt_out = record.get("user_intent") in ["STOP", "DO_NOT_DISTURB"]
        if opt_out:
            return {
                "transaction_id": record.get("transaction_id"),
                "customer_name": record.get("customer_name"),
                "failure_type": record.get("failure_type"),
                "amount_inr": record.get("amount_inr", 0),
                "status": "ESCALATED_OPT_OUT",
                "action_taken": "STOP",
                "channel": "NONE",
                "guardrail_triggered": "USER_OPT_OUT_DETECTED",
                "money_recovered": 0,
                "audit_reason": "Hard stop: Customer opted out.",
                "promised_date": None,
                "llm_raw_output": {"diagnosis": "Opt-out detected."}
            }

        attempt = record.get("attempt", 1)
        if attempt >= MAX_ATTEMPTS:
            # FIX: distinct status from opt-out, so the two guardrails are distinguishable downstream
            return {
                "transaction_id": record.get("transaction_id"),
                "customer_name": record.get("customer_name"),
                "failure_type": record.get("failure_type"),
                "amount_inr": record.get("amount_inr", 0),
                "status": "ESCALATED_MAX_ATTEMPTS",
                "action_taken": "ESCALATE_HUMAN",
                "channel": "NONE",
                "guardrail_triggered": "MAX_ATTEMPTS_EXCEEDED",
                "money_recovered": 0,
                "audit_reason": f"Hard stop: Attempt {attempt} >= {MAX_ATTEMPTS}.",
                "promised_date": None,
                "llm_raw_output": {"diagnosis": "Max retries exceeded."}
            }

        # PART 2: THE GEMINI LLM CALL (with retry + fallback)
        formatted_prompt = self.generate_agent_prompt(record)
        agent_decision = self._call_llm_with_retry(formatted_prompt, record)

        # PART 3: MAP THE OUTPUT
        action = agent_decision.get("action", "SEND_REMINDER")
        # FIX: don't reuse "ESCALATED_OPT_OUT" here — that label is reserved for the
        # hard-coded opt-out guardrail above. If the LLM itself chooses to STOP or
        # ESCALATE_HUMAN, label it distinctly so the audit trail isn't misleading.
        status = "RECOVERED" if action not in ["STOP", "ESCALATE_HUMAN"] else "ESCALATED_BY_LLM"

        # FIX: enforce the discount ceiling in code — never trust the LLM's number blindly
        raw_discount = agent_decision.get("suggested_discount_pct", 0.0)
        discount = min(max(raw_discount, 0.0), MAX_DISCOUNT_PCT)
        if raw_discount > MAX_DISCOUNT_PCT:
            logger.warning(
                "LLM suggested discount %.2f%% exceeded cap; clamped to %.2f%%.",
                raw_discount, MAX_DISCOUNT_PCT
            )

        amount = record.get("amount_inr", 0)
        recovered_amount = amount * (1 - discount / 100) if status == "RECOVERED" else 0

        return {
            "transaction_id": record.get("transaction_id"),
            "customer_name": record.get("customer_name"),
            "failure_type": record.get("failure_type"),
            "amount_inr": amount,
            "status": status,
            "action_taken": action,
            "channel": agent_decision.get("channel", "EMAIL"),
            "guardrail_triggered": "DISCOUNT_CAPPED" if raw_discount > MAX_DISCOUNT_PCT else "NONE",
            "money_recovered": round(recovered_amount, 2),
            "audit_reason": agent_decision.get("reason_for_action", "LLM decided."),
            "promised_date": agent_decision.get("promised_date"),
            "llm_raw_output": agent_decision
        }

    def run_batch_recovery(self) -> Dict[str, Any]:
        records = self.load_dataset()
        results = []

        total_risk = 0.0
        total_recovered = 0.0
        escalated_count = 0
        recovered_count = 0

        category_stats = {
            "subscription_mandate": {"at_risk": 0.0, "recovered": 0.0},
            "checkout_abandonment": {"at_risk": 0.0, "recovered": 0.0},
            "b2b_invoice": {"at_risk": 0.0, "recovered": 0.0}
        }

        for record in records:
            res = self.process_record(record)
            results.append(res)

            amt = record.get("amount_inr", 0)
            total_risk += amt

            f_type = record.get("failure_type")
            if f_type in category_stats:
                category_stats[f_type]["at_risk"] += amt

            if res.get("status") == "RECOVERED":
                recovered = res.get("money_recovered", 0)
                total_recovered += recovered
                recovered_count += 1
                if f_type in category_stats:
                    category_stats[f_type]["recovered"] += recovered
            else:
                escalated_count += 1

        recovery_rate = (total_recovered / total_risk * 100) if total_risk > 0 else 0.0

        return {
            "summary": {
                "total_records": len(records),
                "total_risk_inr": total_risk,
                "total_recovered_inr": total_recovered,
                "recovery_rate_pct": round(recovery_rate, 2),
                "successful_recoveries": recovered_count,
                "escalated_opt_outs": escalated_count
            },
            "category_breakdown": category_stats,
            "audit_trail": results
        }