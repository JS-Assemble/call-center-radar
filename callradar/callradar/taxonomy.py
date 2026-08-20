"""Closed intent taxonomy (S6). Derived from real transcripts, not assumed:
extracted the first customer turns across all 1,441 calls, clustered them by
hand, and validated against a 20-call spot check (100% coverage, no forced
`other`) before committing this list — see docs/DECISIONS.md.

This corpus is a tightly scripted synthetic dataset (Little Harper Valley
Bank) covering only 8 real customer-request scenarios, not the 12-18 the
build plan estimated going in — that estimate was generic guidance, not
fitted to this specific corpus. Padding the list to hit a target count would
make trend aggregation less honest, not more, so it stays at 8 + other.

`other` exists for genuine anomalies (multi-intent calls, unrecoverable ASR
garble, mid-call topic changes) — it is not expected to be common.
"""

INTENT_TAXONOMY = [
    "balance_check",
    "transfer_funds",
    "lost_card",
    "new_checkbook",
    "reset_password",
    "branch_hours",
    "pay_bill",
    "schedule_appointment",
    "other",
]

INTENT_DESCRIPTIONS = {
    "balance_check": "Customer asks for their checking or savings account balance.",
    "transfer_funds": "Customer wants to move money between their own accounts.",
    "lost_card": "Customer reports a lost/stolen credit or debit card and wants a replacement.",
    "new_checkbook": "Customer requests a new checkbook mailed to their address.",
    "reset_password": "Customer wants their online banking password reset.",
    "branch_hours": "Customer asks what hours a local branch is open.",
    "pay_bill": "Customer wants to pay a third-party bill (utility, etc.) from their account.",
    "schedule_appointment": "Customer wants to book an appointment at a branch.",
    "other": "Anything that doesn't fit the above — multi-intent, garbled beyond recognition, or a genuine one-off.",
}
