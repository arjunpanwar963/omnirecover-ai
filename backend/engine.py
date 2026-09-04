import json
import os
from typing import Dict, Any, List
import google.generativeai as genai

class OmniRecoverEngine:
    def __init__(self, data_path: str = "data/dataset.json"):
        self.data_path = data_path
        
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            # HARDCODE YOUR KEY HERE JUST FOR THE HACKATHON DEMO IF TERMINAL FAILS
            api_key = "YOUR_API_KEY_HERE" # Removed for public repo

        genai.configure(api_key=api_key)
        
        # Force JSON output directly at the model level
        self.model = genai.GenerativeModel(
            'gemini-1.5-flash',
            generation_config={"response_mime_type": "application/json"}
        )

# ... (keep the rest of your code exactly as it is)
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
        
        return f"""
        You are OmniRecover AI, a zero-trust revenue recovery agent for Razorpay merchants.
        
        **INPUT DATA:**
        - Customer ID: {record.get('transaction_id')}
        - Failure Type: {f_type}
        - Attempt Number: 1
        - Previous Channels Used: NONE
        - Customer Opt-Out Status: {opt_out}
        - Amount: ₹{record.get('amount_inr')}
        
        **NON-NEGOTIABLE RULES (Must strictly follow):**
        1. If `opt_out` is True -> `action: "STOP"`, reason: "Customer opted out".
        2. If `attempt` >= 3 -> `action: "ESCALATE_HUMAN"`, reason: "Max retries exceeded".
        3. Discount ONLY allowed for `CART_ABANDONED`. Max discount = 5%.
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
          "attempt_used": 1,
          "reason_for_action": "String explanation"
        }}
        """

    def _deterministic_fallback(self, record: dict) -> dict:
        """Failsafe if the API key is missing or rate limited."""
        opt_out = record.get("user_intent") in ["STOP", "DO_NOT_DISTURB"]
        is_abandoned = record.get("failure_type") == "checkout_abandonment"
        
        agent_decision = {
            "diagnosis": "Fallback: Customer opted out." if opt_out else f"Fallback: {record.get('failure_type')}",
            "action": "STOP" if opt_out else "SEND_PAYMENT_LINK",
            "channel": "NONE" if opt_out else ("PAYMENT_LINK" if is_abandoned else "WHATSAPP"),
            "recovery_message": "Action halted." if opt_out else f"Hi, complete your payment of ₹{record.get('amount_inr')}.",
            "suggested_discount_pct": 5.0 if (is_abandoned and not opt_out) else 0.0,
            "promised_date": None,
            "attempt_used": 1,
            "reason_for_action": "Deterministic fallback applied."
        }
        return agent_decision

    def process_record(self, record: dict) -> dict:
        # PART 1: HARD SAFETY CHECKS
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
        if attempt >= 3:
            return {
                "transaction_id": record.get("transaction_id"),
                "customer_name": record.get("customer_name"),
                "failure_type": record.get("failure_type"),
                "amount_inr": record.get("amount_inr", 0),
                "status": "ESCALATED_OPT_OUT",
                "action_taken": "ESCALATE_HUMAN",
                "channel": "NONE",
                "guardrail_triggered": "MAX_ATTEMPTS_EXCEEDED",
                "money_recovered": 0,
                "audit_reason": f"Hard stop: Attempt {attempt} >= 3.",
                "promised_date": None,
                "llm_raw_output": {"diagnosis": "Max retries exceeded."}
            }

        # PART 2: THE GEMINI LLM CALL
        try:
            formatted_prompt = self.generate_agent_prompt(record)
            response = self.model.generate_content(
                f"{formatted_prompt}\n\nAnalyze this failure and return the JSON: {json.dumps(record)}"
            )
            agent_decision = json.loads(response.text)

        except Exception as e:
            print(f"⚠️ Gemini API failed: {e}")
            agent_decision = self._deterministic_fallback(record)

        # PART 3: MAP THE OUTPUT
        action = agent_decision.get("action", "SEND_REMINDER")
        status = "RECOVERED" if action not in ["STOP", "ESCALATE_HUMAN"] else "ESCALATED_OPT_OUT"
        
        discount = agent_decision.get("suggested_discount_pct", 0.0)
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
            "guardrail_triggered": "NONE",
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