"""Unit & Period Anchor Engine.

Detects unit declarations (e.g. '₹ in Lakhs', 'Rs in Crores', 'USD Millions',
'in Thousands') and period headers ('As of March 31, 2025', 'FY25 vs FY24')
from financial statement page headers and text blocks.
"""
import re
from dataclasses import dataclass
from typing import Optional, List, Tuple



@dataclass
class UnitInfo:
    unit_name: str         # e.g., "Crores", "Lakhs", "Millions", "Thousands", "Units"
    currency: str          # e.g., "INR", "USD", "EUR", "UNKNOWN"
    multiplier: float      # e.g., Crores -> 10_000_000, Lakhs -> 100_000, Millions -> 1_000_000
    raw_text: str


@dataclass
class PeriodHeader:
    current_period: str    # e.g. "31-Mar-2025" or "FY25"
    prior_period: Optional[str] = None  # e.g. "31-Mar-2024" or "FY24"
    columns_detected: List[str] = None


UNIT_PATTERNS: List[Tuple[str, str, str, float]] = [
    # (regex_pattern, unit_name, currency, multiplier)
    (r"(?:₹|rs\.?|rupees?)\s+(?:in\s+)?crores?", "Crores", "INR", 10_000_000.0),
    (r"(?:₹|rs\.?|rupees?)\s+(?:in\s+)?lakhs?", "Lakhs", "INR", 100_000.0),
    (r"(?:₹|rs\.?|rupees?)\s+(?:in\s+)?millions?", "Millions", "INR", 1_000_000.0),
    (r"(?:₹|rs\.?|rupees?)\s+(?:in\s+)?thousands?", "Thousands", "INR", 1_000.0),
    (r"usd\s+(?:in\s+)?millions?|\$\s+(?:in\s+)?millions?", "Millions", "USD", 1_000_000.0),
    (r"usd\s+(?:in\s+)?thousands?|\$\s+(?:in\s+)?thousands?", "Thousands", "USD", 1_000.0),
    (r"eur|€\s+(?:in\s+)?millions?", "Millions", "EUR", 1_000_000.0),
    (r"in\s+crores?", "Crores", "INR", 10_000_000.0),
    (r"in\s+lakhs?", "Lakhs", "INR", 100_000.0),
    (r"in\s+millions?", "Millions", "UNKNOWN", 1_000_000.0),
    (r"in\s+thousands?", "Thousands", "UNKNOWN", 1_000.0),
]

PERIOD_DATE_PATTERN = re.compile(
    r"(?:as\s+at|as\s+of|for\s+the\s+year\s+ended)?\s*"
    r"(\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2}|fy\s*\d{2,4})",
    re.IGNORECASE
)


def detect_unit(text: str) -> UnitInfo:
    """Scan page or table header text for unit scale declarations."""
    t = text.lower()
    for pattern, name, curr, mult in UNIT_PATTERNS:
        match = re.search(pattern, t)
        if match:
            return UnitInfo(unit_name=name, currency=curr, multiplier=mult, raw_text=match.group(0))

    return UnitInfo(unit_name="Units", currency="UNKNOWN", multiplier=1.0, raw_text="default")


def detect_periods(text: str) -> PeriodHeader:
    """Extract comparative period headers (e.g. 31 March 2025 vs 31 March 2024)."""
    matches = PERIOD_DATE_PATTERN.findall(text)
    if not matches:
        return PeriodHeader(current_period="Current", prior_period="Prior", columns_detected=[])
    
    unique_dates = []
    for m in matches:
        m_str = m.strip()
        if m_str not in unique_dates:
            unique_dates.append(m_str)

    current = unique_dates[0] if len(unique_dates) > 0 else "Current"
    prior = unique_dates[1] if len(unique_dates) > 1 else None
    return PeriodHeader(current_period=current, prior_period=prior, columns_detected=unique_dates)
