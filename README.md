# OmniRecover AI: Multi-Channel Payment & Mandate Recovery Pipeline

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
   pip install -r requirements.txt