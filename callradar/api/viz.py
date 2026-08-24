"""Server-rendered inline SVG — no charting library, consistent with the
project's no-bundler stance. Pure presentation, no DB access.
"""
from markupsafe import escape

_MOOD_MIN, _MOOD_MAX = -1.0, 1.0


def _y(value: float, height: int, pad: float = 8.0) -> float:
    """Map a mood value in [-1, 1] to an SVG y-coordinate (inverted: +1 on top)."""
    span = height - 2 * pad
    frac = (value - _MOOD_MIN) / (_MOOD_MAX - _MOOD_MIN)
    return height - pad - frac * span


def render_mood_timeline_svg(
    points: list[dict], mood_shift: dict | None, width: int = 640, height: int = 120,
) -> str:
    """points: [{"turn_id", "start_s", "value"}] ordered by turn_index (customer
    turns only). mood_shift, if given, is {"turn_id", "mood_from", "mood_to",
    "evidence": {"turn_id", "timestamp_s", "quote"}} — its turn gets a marker
    and its own clickable citation span, reusing citation-seek.js unchanged.
    """
    if not points:
        return ""

    t_min = points[0]["start_s"]
    t_max = points[-1]["start_s"] or 1.0
    span_s = max(t_max - t_min, 1.0)
    pad_x = 8.0

    def x(t: float) -> float:
        return pad_x + (t - t_min) / span_s * (width - 2 * pad_x)

    coords = [(x(p["start_s"]), _y(p["value"], height)) for p in points]
    polyline = " ".join(f"{px:.1f},{py:.1f}" for px, py in coords)

    zero_y = _y(0.0, height)
    markers = []
    shift_turn_id = mood_shift["turn_id"] if mood_shift else None
    for p, (px, py) in zip(points, coords):
        is_shift = p["turn_id"] == shift_turn_id
        r = 5 if is_shift else 2.5
        fill = "#d1451b" if is_shift else "#0b5fff"
        markers.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{r}" fill="{fill}" />')

    shift_label = ""
    if mood_shift:
        shift_label = (
            f'<text x="{width - pad_x:.1f}" y="14" text-anchor="end" font-size="11" fill="#d1451b">'
            f"{escape(mood_shift['mood_from'])} &rarr; {escape(mood_shift['mood_to'])}</text>"
        )

    svg = [
        f'<svg class="mood-timeline" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg">',
        f'<line x1="{pad_x}" y1="{zero_y:.1f}" x2="{width - pad_x}" y2="{zero_y:.1f}" '
        f'stroke="#ddd" stroke-dasharray="3,3" />',
        f'<polyline points="{polyline}" fill="none" stroke="#0b5fff" stroke-width="1.5" />',
        *markers,
        shift_label,
        "</svg>",
    ]

    html = "".join(svg)
    if mood_shift:
        ev = mood_shift["evidence"]
        html += (
            f'<span class="citation" data-seek="{ev["timestamp_s"]}" data-turn-id="{escape(ev["turn_id"])}">'
            f"mood shift evidence: &ldquo;{escape(ev['quote'])}&rdquo;</span>"
        )
    return html


def render_sparkline_svg(values: list[float], width: int = 200, height: int = 30) -> str:
    """values: avg mood per call, in call_date order. Purely decorative — no
    citations, no interaction.
    """
    if not values:
        return ""
    if len(values) == 1:
        cy = _y(values[0], height)
        return (
            f'<svg class="sparkline" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<circle cx="{width / 2:.1f}" cy="{cy:.1f}" r="2.5" fill="#0b5fff" /></svg>'
        )

    pad_x = 4.0
    step = (width - 2 * pad_x) / (len(values) - 1)
    coords = [(pad_x + i * step, _y(v, height)) for i, v in enumerate(values)]
    polyline = " ".join(f"{px:.1f},{py:.1f}" for px, py in coords)
    return (
        f'<svg class="sparkline" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<polyline points="{polyline}" fill="none" stroke="#0b5fff" stroke-width="1.5" /></svg>'
    )
