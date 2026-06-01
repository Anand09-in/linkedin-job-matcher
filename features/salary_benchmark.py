"""
Feature module: salary_benchmark
Salary extraction + local-currency market bands + negotiation guidance.
No LLM — pure regex extraction and lookup tables.
"""
from __future__ import annotations

import re
from typing import Optional

from loguru import logger
from pydantic import BaseModel


# ── Market benchmarks: annual USD by seniority ────────────────────────────────
_SENIORITY_RANGES: dict[str, tuple[float, float, float]] = {
    "Entry":      (40_000,  60_000,  75_000),
    "Junior":     (55_000,  75_000,  95_000),
    "Mid":        (75_000, 100_000, 130_000),
    "Senior":    (110_000, 140_000, 175_000),
    "Lead":      (130_000, 165_000, 210_000),
    "Principal": (155_000, 195_000, 250_000),
    "Manager":   (120_000, 155_000, 200_000),
    "Director":  (160_000, 210_000, 280_000),
}

# Location → (multiplier vs US, local currency, approx conversion rate to USD)
_LOCATION_MAP: dict[str, tuple[float, str, float]] = {
    "india":      (0.20, "INR", 83.0),
    "bangalore":  (0.20, "INR", 83.0),
    "bengaluru":  (0.20, "INR", 83.0),
    "mumbai":     (0.20, "INR", 83.0),
    "hyderabad":  (0.18, "INR", 83.0),
    "chennai":    (0.17, "INR", 83.0),
    "pune":       (0.18, "INR", 83.0),
    "delhi":      (0.19, "INR", 83.0),
    "uk":         (0.75, "GBP", 0.79),
    "london":     (0.85, "GBP", 0.79),
    "germany":    (0.70, "EUR", 0.92),
    "berlin":     (0.72, "EUR", 0.92),
    "canada":     (0.80, "CAD", 1.36),
    "toronto":    (0.83, "CAD", 1.36),
    "australia":  (0.75, "AUD", 1.53),
    "singapore":  (0.85, "SGD", 1.34),
}

_NEGOTIATION_TIPS: dict[str, list[str]] = {
    "Entry": [
        "Anchor to the market midpoint — entry offers often start at the low end",
        "Ask about structured salary review timelines (6- or 12-month check-ins)",
        "Negotiate learning budget, certifications, and conference allowances",
        "Don't accept the first offer; even a 5–10% ask is standard",
    ],
    "Junior": [
        "Benchmark your offer against local market data before responding",
        "Ask for the midpoint if offered the low end — justify with a concrete project outcome",
        "Negotiate sign-on bonus if base is at ceiling",
        "Confirm promotion criteria and timeline in writing",
    ],
    "Mid": [
        "Negotiate total compensation: base + bonus + equity, not just base",
        "Counter with data — cite your matched skills and scarcity in the market",
        "Ask about ESOP / RSU vesting schedules and cliff dates",
        "If base is fixed, negotiate on joining bonus, remote allowance, or extra leave",
    ],
    "Senior": [
        "At this level, equity (RSUs/stock options) can exceed base — always negotiate it",
        "Ask for the compensation band in writing before negotiating",
        "Counter at the top 25% of the band — you have leverage",
        "Negotiate accelerated vesting for unvested equity from your current role",
    ],
    "Lead": [
        "Request the full comp breakdown: base, bonus target, equity refreshes, benefits",
        "Sign-on bonuses of 10–20% of base are standard at this level — ask",
        "Negotiate quarterly equity refreshes for retention after cliff",
        "Clarify decision-making authority and headcount in the offer stage",
    ],
    "Principal": [
        "Negotiate as a senior individual contributor or manager — equity is the primary lever",
        "Ask about performance-based equity multipliers",
        "Discuss the 2-year comp trajectory, not just year 1",
        "Request clarity on the impact scope tied to this level before signing",
    ],
}

_DEFAULT_TIPS = [
    "Research market rates on Glassdoor, Levels.fyi, or AmbitionBox before negotiating",
    "Never give a number first — deflect with 'I'm flexible depending on the full package'",
    "Always negotiate; the worst they can say is no",
    "Get the final offer in writing before resigning from your current role",
]

_BENEFITS_TO_ASK = [
    "Health insurance coverage (self + family)",
    "Annual learning & development budget",
    "Remote/hybrid work policy and equipment allowance",
    "Equity / ESOP / RSU details and vesting schedule",
    "Performance bonus structure and payout history",
    "Paid time off (leaves, public holidays, sick days)",
    "Maternity / paternity / parental leave",
    "Relocation assistance (if applicable)",
    "Pension / PF / retirement contributions",
    "Internet / co-working reimbursement (for remote roles)",
]


class SalaryRange(BaseModel):
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    currency: str = "USD"
    period: str = "annual"
    raw_text: Optional[str] = None


class SalaryBenchmark(BaseModel):
    job_id: str
    job_title: str
    location: Optional[str]
    currency: str
    extracted_salary: Optional[SalaryRange]
    market_low: float
    market_mid: float
    market_high: float
    your_likely_band: str          # low | low-mid | mid | mid-high | high
    negotiation_tips: list[str]
    benefits_to_ask: list[str]
    notes: list[str]


def benchmark_salary(job: dict, candidate_profile: dict) -> SalaryBenchmark:
    """Extract salary, benchmark market range in local currency, and give negotiation guidance."""
    job_id = job.get("id", "")
    job_title = job.get("title", "")
    location = job.get("location", "") or ""
    seniority = job.get("seniority_level", "Mid") or "Mid"
    salary_raw = job.get("salary_range", "") or ""
    description = job.get("description", "") or ""
    total_exp = candidate_profile.get("total_experience_years") or 0

    extracted = _parse_salary(salary_raw) or _extract_from_description(description)

    multiplier, currency, fx = _get_location_info(location)
    low_usd, mid_usd, high_usd = _SENIORITY_RANGES.get(seniority, _SENIORITY_RANGES["Mid"])

    # Convert to local currency
    low  = round(low_usd  * multiplier * fx)
    mid  = round(mid_usd  * multiplier * fx)
    high = round(high_usd * multiplier * fx)

    your_band = _estimate_band(total_exp)
    neg_tips = _NEGOTIATION_TIPS.get(seniority, _DEFAULT_TIPS)
    notes = _build_notes(extracted, currency, location)

    logger.debug(
        f"[Salary] job={job_id} seniority={seniority} location={location} "
        f"currency={currency} market={low:,.0f}–{high:,.0f}"
    )

    return SalaryBenchmark(
        job_id=job_id,
        job_title=job_title,
        location=location or None,
        currency=currency,
        extracted_salary=extracted,
        market_low=low,
        market_mid=mid,
        market_high=high,
        your_likely_band=your_band,
        negotiation_tips=neg_tips,
        benefits_to_ask=_BENEFITS_TO_ASK,
        notes=notes,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_location_info(location: str) -> tuple[float, str, float]:
    """Return (col_multiplier, currency, fx_rate_to_local)."""
    if location:
        loc_lower = location.lower()
        for region, (mult, curr, fx) in _LOCATION_MAP.items():
            if region in loc_lower:
                return mult, curr, fx
    return 1.0, "USD", 1.0


def _estimate_band(total_exp: float) -> str:
    """Estimate which part of the market band the candidate likely sits in."""
    if total_exp <= 1:
        return "low"
    elif total_exp <= 3:
        return "low-mid"
    elif total_exp <= 6:
        return "mid"
    elif total_exp <= 10:
        return "mid-high"
    else:
        return "high"


def _parse_salary(text: str) -> Optional[SalaryRange]:
    if not text or not text.strip():
        return None
    patterns = [
        r"[\$₹£€]?\s*(\d[\d,\.]+)\s*[kK]?\s*[-–to]+\s*[\$₹£€]?\s*(\d[\d,\.]+)\s*[kK]?",
        r"(\d[\d,\.]+)\s*[kK]?\s*[-–to]+\s*(\d[\d,\.]+)\s*[kK]?",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                lo = _parse_number(m.group(1))
                hi = _parse_number(m.group(2))
                currency = "USD"
                if "₹" in text or "INR" in text.upper():
                    currency = "INR"
                    if re.search(r"[Ll](?:akh)?|lpa", text, re.IGNORECASE):
                        lo *= 100_000
                        hi *= 100_000
                elif "£" in text or "GBP" in text.upper():
                    currency = "GBP"
                elif "€" in text or "EUR" in text.upper():
                    currency = "EUR"
                elif re.search(r"\d\s*[kK]\b", text):
                    lo *= 1_000
                    hi *= 1_000
                return SalaryRange(min_amount=lo, max_amount=hi, currency=currency, raw_text=text)
            except (ValueError, IndexError):
                pass
    return SalaryRange(raw_text=text)


def _extract_from_description(description: str) -> Optional[SalaryRange]:
    if not description:
        return None
    salary_lines = " ".join(
        line for line in description.split("\n")
        if any(kw in line.lower() for kw in ["salary", "compensation", "ctc", "package", "₹", "$", "lpa", "per annum"])
    )
    return _parse_salary(salary_lines.strip()) if salary_lines.strip() else None


def _parse_number(s: str) -> float:
    return float(re.sub(r"[,\s]", "", s))


def _build_notes(
    extracted: Optional[SalaryRange],
    currency: str,
    location: str,
) -> list[str]:
    notes: list[str] = []
    if not extracted or (not extracted.min_amount and not extracted.max_amount):
        notes.append(
            "Salary not stated in the posting — use market estimates as your anchor "
            "and ask for the band during the first screening call"
        )
    if currency != "USD":
        notes.append(f"Market estimates shown in {currency} (adjusted for {location})")
    notes.append(
        "Benchmarks are based on industry averages — actual offers vary significantly "
        "by company stage, funding, and equity component"
    )
    return notes
