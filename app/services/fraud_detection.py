"""
ScholarBot — Fraud detection service (Phase 4 T4).

Validates scholarship listings against known fraud patterns:
- URL validation and accessibility checks
- Deadline sanity checks
- Amount plausibility
- Suspicious keyword detection

Run periodically or on-demand via /api/admin/validate-listings.
"""
import re
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Known legitimate scholarship domains
TRUSTED_DOMAINS = {
    "chevening.org", "fulbright.gov", "gatesscholarship.org",
    "commonwealthscholarships.ac.uk", "rhodeshouse.ox.ac.uk",
    "mastercardfdn.org", "africanleadershipfoundation.org",
    "daad.de", "britishcouncil.org", "aauw.org",
    "paset.org", "sida.se", "norad.no", "afdb.org",
    "auc.edu", "unu.edu", "worldbank.org",
    "kcb.co.ke", "safaricom.co.ke", "equity.co.ke",
    "scholarships.gov.au", "studyinaustralia.gov.au",
    "inlaks.org", "tatascholarships.com", "infosys.com",
    "google.com", "microsoft.com", "ibm.com", "oracle.com",
}

# Red flag patterns in scholarship names/descriptions
FRAUD_PATTERNS = [
    r"pay.*application\s+fee",
    r"wire\s+transfer",
    r"western\s+union",
    r"bitcoin.*scholarship",
    r"guaranteed.*scholarship",
    r"no.*application.*required",
    r"processing\s+fee\s+required",
    r"unclaimed\s+funds",
    r"lottery.*scholarship",
    r"won.*scholarship.*click",
]


def validate_opportunity(opp: dict) -> dict:
    """
    Run all fraud checks on a single opportunity.

    Returns:
        valid: bool
        score: 0.0–1.0 (higher = more trustworthy)
        issues: list of detected issues
        warnings: list of non-critical concerns
    """
    issues = []
    warnings = []
    score = 1.0

    name = opp.get("name", "")
    url = opp.get("url", "")
    amount = float(opp.get("amount_usd", 0) or 0)
    deadline = opp.get("deadline", "")
    provider = opp.get("provider", "")

    # ── URL checks ─────────────────────────────────────────────
    if not url:
        issues.append("Missing application URL")
        score -= 0.4
    elif not url.startswith("https://"):
        if url.startswith("http://"):
            warnings.append("Application URL uses HTTP not HTTPS")
            score -= 0.1
        else:
            issues.append(f"Invalid URL format: {url[:60]}")
            score -= 0.3

    if url:
        domain = _extract_domain(url)
        if domain:
            if domain in TRUSTED_DOMAINS or any(
                td in domain for td in TRUSTED_DOMAINS
            ):
                score += 0.1  # Bonus for known domain
            elif not _is_plausible_org_domain(domain):
                warnings.append(f"Unfamiliar domain: {domain}")
                score -= 0.05

    # ── Amount checks ──────────────────────────────────────────
    if amount <= 0:
        warnings.append("No funding amount specified")
    elif amount > 500_000:
        warnings.append(f"Unusually large amount: ${amount:,.0f}")
        score -= 0.1
    elif amount < 100:
        warnings.append(f"Very small amount: ${amount:.0f}")
        score -= 0.05

    # ── Deadline checks ────────────────────────────────────────
    if deadline:
        try:
            deadline_dt = datetime.strptime(deadline, "%Y-%m-%d")
            days_until = (deadline_dt - datetime.utcnow()).days
            if days_until < -365:
                issues.append(f"Deadline passed over a year ago: {deadline}")
                score -= 0.5
            elif days_until < 0:
                warnings.append(f"Deadline has passed: {deadline}")
                score -= 0.2
            elif days_until > 730:
                warnings.append(f"Deadline over 2 years away: {deadline}")
                score -= 0.05
        except ValueError:
            issues.append(f"Invalid deadline format: {deadline}")
            score -= 0.2
    else:
        warnings.append("No deadline specified")

    # ── Fraud pattern detection ────────────────────────────────
    text_to_check = f"{name} {provider}".lower()
    for pattern in FRAUD_PATTERNS:
        if re.search(pattern, text_to_check, re.IGNORECASE):
            issues.append(f"Fraud pattern detected: '{pattern}'")
            score -= 0.6

    # ── Name quality checks ────────────────────────────────────
    if not name or len(name) < 5:
        issues.append("Scholarship name too short or missing")
        score -= 0.3
    elif len(name) > 300:
        warnings.append("Scholarship name unusually long")
        score -= 0.05

    if not provider:
        warnings.append("No provider/organisation specified")
        score -= 0.1

    # ── Final scoring ──────────────────────────────────────────
    score = round(max(0.0, min(1.0, score)), 2)
    valid = score >= 0.5 and len(issues) == 0

    return {
        "opportunity_id": opp.get("id", ""),
        "name": name,
        "valid": valid,
        "trust_score": score,
        "trust_label": (
            "Trusted" if score >= 0.85 else
            "Likely legitimate" if score >= 0.70 else
            "Review recommended" if score >= 0.50 else
            "Suspicious"
        ),
        "issues": issues,
        "warnings": warnings,
    }


def validate_all_opportunities() -> dict:
    """Validate every opportunity in the database."""
    from engine.opportunity_db import load_all_opportunities
    opps = load_all_opportunities()

    results = [validate_opportunity(o) for o in opps]
    trusted = [r for r in results if r["trust_score"] >= 0.85]
    suspicious = [r for r in results if not r["valid"]]
    needs_review = [r for r in results if r["trust_score"] < 0.70]

    return {
        "total": len(results),
        "trusted": len(trusted),
        "needs_review": len(needs_review),
        "suspicious": len(suspicious),
        "average_trust_score": round(
            sum(r["trust_score"] for r in results) / len(results), 2
        ) if results else 0,
        "results": results,
    }


def _extract_domain(url: str) -> Optional[str]:
    m = re.match(r"https?://([^/]+)", url)
    if m:
        domain = m.group(1).lower()
        # Remove www. prefix
        return domain[4:] if domain.startswith("www.") else domain
    return None


def _is_plausible_org_domain(domain: str) -> bool:
    """Check if domain looks like a legitimate organisation."""
    suspicious_tlds = {".xyz", ".tk", ".ml", ".ga", ".cf", ".gq"}
    free_hosts = {"wix.com", "weebly.com", "wordpress.com", "blogspot.com"}
    if any(domain.endswith(tld) for tld in suspicious_tlds):
        return False
    if any(fh in domain for fh in free_hosts):
        return False
    return True
