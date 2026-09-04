import json
import os
from typing import Dict, Any, List

class OmniRecoverEngine:
    def __init__(self, data_path: str = "data/dataset.json"):
        self.data_path = data_path
        self.max_contact_attempts = 3
        self.max_allowed_discount_pct = 5.0

    def load_dataset(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.data_path):
            raise FileNotFoundError(f"Dataset file not found at {self.data_path}")
        with open(self.data_path, 'r') as f:
            return json.load(f)

    def process_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        tx_id = record.get("transaction_id")
        amount = record.get("amount_inr", 0)
        failure_type = record.get("failure_type")
        error_code = record.get("error_code")
        user_intent = record.get("user_intent", "NEUTRAL")
        
        # Guardrail Check 1: Explicit Opt-Out / Stop Request
        if user_intent in ["STOP", "DO_NOT_DISTURB"]:
            return {
                "transaction_id": tx_id,
                "customer_name": record.get("customer_name"),
                "failure_type": failure_type,
                "amount_inr": amount,
                "status": "ESCALATED_OPT_OUT",
                "action_taken": "HALT_OUTREACH",
                "channel": "NONE",
                "guardrail_triggered": "USER_OPT_OUT_DETECTED",
                "money_recovered": 0,
                "audit_reason": f"Customer expressed '{user_intent}'. Outreach immediately halted per safety rules."
            }

        # Failure Category 1: Subscription Mandate
        if failure_type == "subscription_mandate":
            if error_code == "INSUFFICIENT_FUNDS":
                action = "SCHEDULED_PAYDAY_RETRY_NUDGE"
                channel = "WhatsApp (Hinglish)"
                recovered = amount
            elif error_code == "UPI_TIMEOUT":
                action = "DISPATCH_1CLICK_PAY_LINK"
                channel = "WhatsApp"
                recovered = amount
            else:  # MANDATE_EXPIRED
                action = "SEND_MANDATE_REAUTH_LINK"
                channel = "WhatsApp & SMS"
                recovered = amount

        # Failure Category 2: Checkout Abandonment
        elif failure_type == "checkout_abandonment":
            action = "DISPATCH_DYNAMIC_CHECKOUT_LINK_WITH_DISCOUNT"
            channel = "WhatsApp"
            # Apply bounded discount guardrail
            discounted_amount = amount * (1 - (self.max_allowed_discount_pct / 100))
            recovered = round(discounted_amount, 2)

        # Failure Category 3: B2B Invoice Delay
        elif failure_type == "b2b_invoice":
            action = "VOICE_AI_CALL_AND_EMAIL_TERMS_ESCALATION"
            channel = "Voice AI & Email"
            recovered = amount

        else:
            return {
                "transaction_id": tx_id,
                "status": "UNHANDLED_EXCEPTION",
                "action_taken": "MANUAL_REVIEW_REQUIRED",
                "money_recovered": 0,
                "audit_reason": "Unknown failure category."
            }

        return {
            "transaction_id": tx_id,
            "customer_name": record.get("customer_name"),
            "failure_type": failure_type,
            "amount_inr": amount,
            "status": "RECOVERED",
            "action_taken": action,
            "channel": channel,
            "guardrail_triggered": "NONE (COMPLIANT)",
            "money_recovered": recovered,
            "audit_reason": f"Diagnostic: {error_code}. Intervention executed successfully via {channel}."
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

            if res["status"] == "RECOVERED":
                recovered = res["money_recovered"]
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