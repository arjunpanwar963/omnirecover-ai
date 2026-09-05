<!-- # OmniRecover AI: Multi-Channel Payment & Mandate Recovery Pipeline

## Overview
OmniRecover AI is an autonomous, multi-channel payment recovery engine built to close lost revenue loops for Razorpay merchants across Subscriptions, Abandoned Checkouts, and Overdue B2B Invoices.

## Key Architecture & Guardrails
- **Multi-Failure Diagnostic Core:** Evaluates error codes across subscription mandates, checkout timeouts, and B2B invoice delays.
- **Deterministic Guardrails:**
  - Hard limit of maximum 3 contact attempts.
  - Automatic halt upon user opt-out detection ("STOP" / "DO_NOT_DISTURB").
  - Maximum 5% bounded discount limit for abandonment nudges.
- **Auditability:** Complete JSON audit trail generated for every decision.

## How to Run Locally
1. Clone repository & install dependencies:
   ```bash
   pip install -r requirements.txt -->
   # 🔁 OmniRecover AI

**Autonomous, multi-channel payment & mandate recovery for Razorpay merchants.**

OmniRecover AI closes lost-revenue loops across three of the most common leak points in a subscription business: failed subscription mandates, abandoned checkouts, and overdue B2B invoices — all with hard-coded safety guardrails so automation never crosses the line into spam or overreach.

<p>
  <img alt="status" src="https://img.shields.io/badge/status-early--stage-orange">
  <img alt="python" src="https://img.shields.io/badge/python-3.9%2B-blue">
  <img alt="stars" src="https://img.shields.io/github/stars/arjunpanwar963/omnirecover-ai">
</p>

---

## Table of Contents

- [Why OmniRecover AI](#why-omnirecover-ai)
- [How It Works](#how-it-works)
- [Guardrails](#guardrails)
- [Architecture](#architecture)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Usage](#usage)
- [Audit Trail](#audit-trail)
- [Roadmap](#roadmap)
- [Contributing](#contributing)

---

## Why OmniRecover AI

Every Razorpay merchant leaks revenue in the same three places:

| Leak point | Typical cause | Cost |
|---|---|---|
| **Failed subscription mandates** | Expired cards, insufficient funds, bank declines | Silent subscriber churn |
| **Abandoned checkouts** | Payment friction, distraction, price hesitation | Lost one-time sales |
| **Overdue B2B invoices** | Manual follow-up, no consistent cadence | Cash-flow drag |

Most recovery tools handle exactly one of these. **OmniRecover AI treats all three as instances of the same problem** — a failure event that needs a diagnosis, a channel, and a bounded, auditable response — and recovers revenue across all of them from a single pipeline.

## How It Works

```
 Failure Event
      │
      ▼
┌─────────────────────┐
│ Diagnostic Core      │  ← classifies error type (mandate / checkout / invoice)
└─────────┬────────────┘
          ▼
┌─────────────────────┐
│ Guardrail Engine      │  ← checks attempt count, opt-out status, discount bounds
└─────────┬────────────┘
          ▼
┌─────────────────────┐
│ Channel Router        │  ← Email / WhatsApp / Telegram / SMS
└─────────┬────────────┘
          ▼
┌─────────────────────┐
│ Audit Logger          │  ← writes a JSON record of every decision
└─────────────────────┘
```

1. **Diagnostic Core** ingests the failure (a declined mandate, a stalled checkout, a past-due invoice) and classifies *why* it happened.
2. **Guardrail Engine** decides whether it's even allowed to act — has this customer already been contacted 3 times? Have they opted out? Is a proposed discount within the allowed bound?
3. **Channel Router** picks the best channel for that customer and failure type.
4. **Audit Logger** writes a complete, structured record of the decision — what happened, why, and what the system did about it.

## Guardrails

OmniRecover AI is built on the principle that **autonomy without limits isn't autonomy, it's risk.** Every action passes through deterministic, non-negotiable checks before it happens:

- 🚦 **3-attempt ceiling** — no customer is contacted more than three times per recovery case, full stop.
- 🛑 **Instant opt-out honoring** — any inbound `STOP` / `DO_NOT_DISTURB` (or equivalent) immediately and permanently halts outreach for that customer.
- 💸 **Bounded discounting** — abandonment nudges are capped at a maximum 5% discount; the system cannot improvise beyond this.
- 🧾 **Full auditability** — every decision, not just every action, is logged as structured JSON — including the ones the system chose *not* to take, and why.

These aren't configurable-away defaults — they're the load-bearing walls of the system.

## Architecture

```
omnirecover-ai/
├── app.py              # Entry point — orchestrates the recovery pipeline
├── backend/            # Diagnostic core, guardrail engine, channel adapters
├── data/                # Sample/event data used by the pipeline
├── requirements.txt     # Python dependencies
└── README.md
```

**Stack:** Python, WooCommerce/Razorpay-style Action-Scheduler-driven jobs, pluggable channel adapters (Email, WhatsApp via UltraMsg, Telegram, SMS via Twilio).

## Getting Started

### Prerequisites

- Python 3.9+
- A Razorpay merchant account
- (Optional) API credentials for the channels you want to enable — Twilio (SMS), UltraMsg (WhatsApp), Telegram Bot API

### Installation

```bash
git clone https://github.com/arjunpanwar963/omnirecover-ai.git
cd omnirecover-ai
pip install -r requirements.txt
```

### Run locally

```bash
python app.py
```

## Configuration

Channel credentials are **optional and additive** — nothing is sent anywhere until a channel is explicitly configured. Set the ones you need as environment variables:

```bash
export RAZORPAY_KEY_ID="..."
export RAZORPAY_KEY_SECRET="..."

# Optional, per channel
export TWILIO_ACCOUNT_SID="..."
export TWILIO_AUTH_TOKEN="..."
export ULTRAMSG_INSTANCE_ID="..."
export ULTRAMSG_TOKEN="..."
export TELEGRAM_BOT_TOKEN="..."
```

> No credentials configured for a channel = that channel is silently skipped, not disabled with an error. This keeps the pipeline safe to run in partial/dev setups.

## Usage

A minimal run against a sample failure event:

```python
from backend.pipeline import run_recovery

event = {
    "type": "subscription_mandate_failure",
    "customer_id": "cust_123",
    "error_code": "MANDATE_DECLINED",
}

decision = run_recovery(event)
print(decision)
```

## Audit Trail

Every decision — action taken or *not* taken — produces a structured record:

```json
{
  "event_id": "evt_8841",
  "customer_id": "cust_123",
  "failure_type": "subscription_mandate_failure",
  "attempt_number": 1,
  "channel_selected": "whatsapp",
  "discount_offered_pct": 0,
  "opt_out_status": false,
  "action": "sent_recovery_message",
  "reasoning": "First contact attempt; customer has not opted out; no discount required for mandate-type failure.",
  "timestamp": "2026-09-05T10:12:00Z"
}
```

This gives merchants (and auditors) a complete, replayable record of every automated decision — not just a log line, but the *why*.

## Roadmap

- [ ] Automated test suite for the Guardrail Engine
- [ ] CI pipeline (GitHub Actions) running on every push
- [ ] Retry-with-backoff and timeout handling for all external API calls
- [ ] Admin dashboard for reviewing audit trails without parsing JSON
- [ ] Configurable guardrail thresholds (with safe, documented defaults)
- [ ] Multi-currency / multi-region support beyond Razorpay

## Contributing

Contributions, issues, and feature requests are welcome. If you're picking this up:

1. Fork the repo and create a feature branch
2. Add tests for any change touching the Guardrail Engine
3. Open a PR describing the *why*, not just the *what*

---

<p align="center"><i>Built to recover revenue without ever recovering it recklessly.</i></p>