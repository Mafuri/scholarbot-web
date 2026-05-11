"""
ScholarBot — GPA normalisation for international scales.

Converts any GPA scale to the US 4.0 standard used internally.
Supports: 4.0 (US), 5.0 (Nigeria/Pakistan), 7.0 (Australia),
10.0 (India), 20.0 (France/Lebanon), 100.0 (percentage).
"""

# Scale detection thresholds
_SCALE_BREAKPOINTS = [
    (4.5,   4.0),   # US / Canada / Kenya
    (5.5,   5.0),   # Nigeria, Pakistan, some African universities
    (6.5,   6.0),   # Some European universities
    (7.5,   7.0),   # Australia, New Zealand
    (10.5,  10.0),  # India (CGPA)
    (21.0,  20.0),  # France, Lebanon (note sur 20)
    (float("inf"), 100.0),  # Percentage-based
]

# Country → typical scale mapping for explicit conversion
COUNTRY_SCALES: dict[str, float] = {
    "kenya": 4.0,
    "united states": 4.0,
    "usa": 4.0,
    "canada": 4.0,
    "nigeria": 5.0,
    "pakistan": 4.0,
    "south africa": 7.0,
    "australia": 7.0,
    "new zealand": 7.0,
    "india": 10.0,
    "france": 20.0,
    "lebanon": 20.0,
    "germany": 1.0,   # German scale is inverted (1 = best, 5 = worst)
    "ethiopia": 4.0,
    "ghana": 4.0,
    "tanzania": 4.0,
    "uganda": 4.0,
    "rwanda": 4.0,
    "senegal": 20.0,
    "cameroon": 20.0,
    "egypt": 100.0,
    "china": 100.0,
    "uk": 100.0,      # UK uses percentage, mapped to 4.0 via class
    "united kingdom": 100.0,
}

# UK degree classifications → 4.0 GPA mapping
UK_CLASSIFICATIONS = {
    "first": 4.0,
    "1st": 4.0,
    "upper second": 3.3,
    "2:1": 3.3,
    "lower second": 2.7,
    "2:2": 2.7,
    "third": 2.0,
    "3rd": 2.0,
}

# German grade → 4.0 GPA (inverted scale, 1.0 = best)
GERMAN_TO_US = {
    1.0: 4.0, 1.3: 3.7, 1.7: 3.3, 2.0: 3.0,
    2.3: 2.7, 2.7: 2.3, 3.0: 2.0, 3.3: 1.7,
    3.7: 1.3, 4.0: 1.0, 5.0: 0.0,
}


def detect_scale(gpa: float) -> float:
    """Infer the likely scale from the GPA value alone."""
    if gpa <= 0:
        return 4.0
    for threshold, scale in _SCALE_BREAKPOINTS:
        if gpa < threshold:
            return scale
    return 100.0


def normalise_gpa(
    gpa: float,
    scale: float = 0.0,
    country: str = "",
) -> dict:
    """
    Normalise any GPA to US 4.0 scale.

    Args:
        gpa:     Raw GPA value as entered by user
        scale:   Explicit scale (0 = auto-detect)
        country: Country of study for scale hints

    Returns dict with:
        gpa_4:     Normalised 4.0 GPA
        scale:     Detected or provided scale
        original:  Original value
        label:     Human-readable description
        confidence: "high" | "medium" | "low"
    """
    if gpa <= 0:
        return {
            "gpa_4": 0.0, "scale": 4.0,
            "original": gpa, "label": "Not provided",
            "confidence": "high",
        }

    country_lower = (country or "").lower().strip()

    # ── German inverted scale ─────────────────────────────────
    if country_lower == "germany" or (scale == 1.0 and gpa <= 5.0):
        # Find nearest German grade
        nearest = min(GERMAN_TO_US.keys(), key=lambda x: abs(x - gpa))
        gpa_4 = GERMAN_TO_US[nearest]
        return {
            "gpa_4": round(gpa_4, 2), "scale": 5.0,
            "original": gpa,
            "label": f"{gpa}/5.0 (German) → {gpa_4}/4.0",
            "confidence": "high" if country_lower == "germany" else "medium",
        }

    # ── Determine scale ───────────────────────────────────────
    if scale and scale > 0:
        used_scale = scale
        confidence = "high"
    elif country_lower in COUNTRY_SCALES:
        used_scale = COUNTRY_SCALES[country_lower]
        confidence = "high"
    else:
        used_scale = detect_scale(gpa)
        confidence = "medium" if gpa > 4.0 else "low"

    # ── Special case: already on 4.0 scale ────────────────────
    if used_scale == 4.0:
        gpa_4 = min(4.0, round(gpa, 2))
        return {
            "gpa_4": gpa_4, "scale": 4.0,
            "original": gpa,
            "label": f"{gpa}/4.0",
            "confidence": confidence,
        }

    # ── Proportional conversion ───────────────────────────────
    gpa_4 = min(4.0, round((gpa / used_scale) * 4.0, 2))
    label = f"{gpa}/{used_scale} → {gpa_4}/4.0"
    if country_lower:
        label = f"{gpa}/{used_scale} ({country.title()}) → {gpa_4}/4.0"

    return {
        "gpa_4": gpa_4,
        "scale": used_scale,
        "original": gpa,
        "label": label,
        "confidence": confidence,
    }


def display_gpa(user_dict: dict) -> str:
    """Return human-readable GPA string for UI display."""
    orig = user_dict.get("gpa_original")
    scale = user_dict.get("gpa_scale", 4.0)
    gpa4 = user_dict.get("gpa", 0.0)
    if orig and scale and scale != 4.0:
        return f"{orig}/{scale} (≈ {gpa4}/4.0)"
    return f"{gpa4}/4.0"
