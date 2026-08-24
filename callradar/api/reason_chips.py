"""Short "why does this call need attention" badges for the dashboard.

Derived entirely from s6_score.py's already-computed `breakdown` JSON — zero
extra signal queries per row. Thresholds are read as a ratio against each
component's own weight (from callradar/stages/s6_score.py's WEIGHTS/formula),
so they track the scorer if its weights ever change.

Upgrade path (not done here): querying `signals` grouped by call_id/type would
give exact counts ("3 dead-air gaps" instead of "high dead air") for one
cheap `call_id IN (...)` query across the whole page — reasonable follow-up,
skipped for now since the ratio alone needs no new queries.
"""

Chip = tuple[str, str]  # (label, severity) — severity in {"danger", "warning", "muted"}


def derive_chips(resolution: str | None, validated: int | None, breakdown: dict | None) -> list[Chip]:
    chips: list[Chip] = []

    if not validated:
        chips.append(("unvalidated", "muted"))
    elif resolution == "unresolved":
        chips.append(("unresolved", "danger"))
    elif resolution == "escalated":
        chips.append(("escalated", "warning"))

    if breakdown:
        if breakdown.get("mood_avg", 1.0) / 0.25 < 0.4:
            chips.append(("mood drop", "warning"))
        if breakdown.get("dead_air_penalty", 1.0) / 0.15 <= 0.6:
            chips.append(("high dead air", "warning"))
        if breakdown.get("talk_over_penalty", 1.0) / 0.10 <= 0.6:
            chips.append(("talk-over", "warning"))
        if breakdown.get("repeat_question_penalty", 1.0) / 0.15 <= 0.75:
            chips.append(("repeat questions", "muted"))

    return chips
