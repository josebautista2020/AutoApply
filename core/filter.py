"""Job filter and scoring engine.

Implements: FR-044 (job scoring), FR-045 (ATS detection).

Scores jobs 0-100 based on title match, salary match, location match,
and keyword match. Applies hard disqualifiers for excluded keywords,
blacklisted companies, and duplicate jobs.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.search.base import RawJob
    from config.settings import AppConfig
    from db.database import Database


@dataclass
class ScoredJob:
    """A job after scoring — includes match score and pass/fail verdict."""

    id: str  # UUID for filename generation
    raw: "RawJob"
    score: int
    pass_filter: bool
    skip_reason: str | None
    eligibility_note: str | None = None
    priority_reasons: list[str] = field(default_factory=list)


# ATS fingerprints for URL-based detection
ATS_FINGERPRINTS = {
    "greenhouse.io": "greenhouse",
    "lever.co": "lever",
    "myworkdayjobs.com": "workday",
    "ashbyhq.com": "ashby",
    "taleo.net": "taleo",
    "icims.com": "icims",
    "linkedin.com/jobs": "linkedin",
    "linkedin.com": "linkedin",
    "indeed.com": "indeed",
}


def detect_ats(url: str) -> str | None:
    """Detect ATS platform from a job URL.

    Args:
        url: The apply URL to check.

    Returns:
        ATS name string or None if unrecognized.
    """
    url_lower = url.lower()
    for domain, ats in ATS_FINGERPRINTS.items():
        if domain in url_lower:
            return ats
    return None


def _confirmed_country(location: str, countries: list[str]) -> bool:
    """Match a country as a location component, not as part of a city name."""
    parts = {part.strip().casefold() for part in re.split(r",|\||\s+-\s+|[()]", location)}
    return any(country.strip().casefold() in parts for country in countries if country.strip())


def _eligibility(job: "RawJob", criteria) -> tuple[bool, str]:
    """Identify explicit sponsorship conflicts; leave other cases for review.

    Job descriptions are incomplete and may be truncated by a search portal.
    A positive sponsorship phrase is therefore a clue, never proof of eligibility.
    """
    countries = criteria.target_countries
    parts = {part.strip().casefold() for part in re.split(r",|\||\s+-\s+|[()]", job.location)}
    country = next((c for c in countries if c.strip().casefold() in parts), None)
    if country is None:
        return False, "Country not confirmed in job location"

    statuses = getattr(criteria, "work_authorization", {})
    status = statuses.get(country, "unknown")
    description = job.description.casefold()
    no_sponsorship = bool(re.search(
        r"\b(?:no|without|unable to provide|cannot provide|will not provide)\s+"
        r"(?:visa\s+)?sponsorship\b(?!\s+(?:required|needed))"
        r"|\bsponsorship\s+(?:is\s+)?not\s+available\b"
        r"|\b(?:will not|cannot|unable to)\s+sponsor\s+(?:work\s+)?visas?\b",
        description,
    ))
    if status == "needs_sponsorship" and no_sponsorship:
        return False, f"{country}: sponsorship required, listing explicitly excludes it"
    if status == "needs_sponsorship":
        return True, f"{country}: sponsorship required; confirm employer support before applying"
    if status == "authorized":
        return True, f"{country}: applicant reports authorization; confirm role restrictions"
    return True, f"{country}: work authorization unverified; check before applying"


_LEADERSHIP_SIGNALS = (
    ("lead", "liderar", "liderazgo"),
    ("manage", "gestionar", "gestion"),
    ("team", "equipo", "equipos"),
    ("strategy", "estrategia"),
    ("roadmap", "hoja de ruta"),
    ("stakeholder", "partes interesadas"),
    ("budget", "presupuesto"),
    ("governance", "gobernanza", "gobierno"),
    ("mentor", "mentoria"),
    ("organizational", "organizacional"),
)
_ARCHITECTURE_SIGNALS = (
    ("architecture", "arquitectura"),
    ("cloud", "nube"),
    ("platform", "plataforma", "plataformas"),
    ("infrastructure", "infraestructura"),
    ("migration", "migracion", "migraciones"),
    ("devsecops",),
    ("kubernetes",),
    ("resilience", "resiliencia"),
    ("security", "seguridad", "ciberseguridad"),
    ("saas",),
)


def _fold_accents(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


def _matching_signals(
    description: str, concepts: tuple[tuple[str, ...], ...], limit: int
) -> list[str]:
    """Count each English/Spanish role concept once, matching complete terms."""
    folded = _fold_accents(description)
    matches = []
    for aliases in concepts:
        match = next((
            alias for alias in aliases
            if re.search(rf"\b{re.escape(_fold_accents(alias))}\b", folded)
        ), None)
        if match:
            matches.append(match)
    return matches[:limit]


def _score_executive(raw_job: "RawJob", criteria) -> tuple[int, list[str]]:
    """Prioritize executive postings with explicit role scope; no salary guesses."""
    title = raw_job.title.casefold()
    reasons: list[str] = []
    title_points = 0
    for target in criteria.job_titles:
        target_lower = target.casefold()
        if target_lower in title:
            title_points = 35
            reasons.append(f"Title: {target} (35)")
            break
        target_words = set(target_lower.split())
        if target_words and len(target_words & set(title.split())) >= len(target_words) * 0.5:
            title_points = 20
    if title_points == 20:
        reasons.append("Title: partial overlap (20)")

    location_points = 0
    if criteria.remote_only:
        if "remote" in raw_job.location.casefold():
            location_points = 20
    elif criteria.target_countries:
        if _confirmed_country(raw_job.location, criteria.target_countries):
            location_points = 20
    elif any(loc.casefold() in raw_job.location.casefold() for loc in criteria.locations):
        location_points = 20
    if location_points:
        reasons.append(f"Location: {raw_job.location} (20)")

    description = raw_job.description.casefold()
    leadership = _matching_signals(description, _LEADERSHIP_SIGNALS, 5)
    architecture = _matching_signals(description, _ARCHITECTURE_SIGNALS, 4)
    if leadership:
        reasons.append(f"Leadership scope: {', '.join(leadership)} ({len(leadership) * 5})")
    if architecture:
        reasons.append(f"Technical scope: {', '.join(architecture)} ({len(architecture) * 5})")
    return title_points + location_points + len(leadership) * 5 + len(architecture) * 5, reasons


def score_job(
    raw_job: "RawJob",
    config: "AppConfig",
    db: "Database | None" = None,
) -> ScoredJob:
    """Score a job against user criteria and return a ScoredJob.

    Scoring breakdown (0-100):
      - Title match: 0-35 points
      - Salary match: 0-20 points
      - Location match: 0-20 points
      - Keyword match: 0-25 points

    Hard disqualifiers (score=0):
      - Exclude keyword found in title or description
      - Company in blacklist
      - Job already in database (deduplication)

    Args:
        raw_job: The unscored job listing.
        config: Application configuration with search criteria.
        db: Optional database for deduplication check.

    Returns:
        ScoredJob with score, pass/fail, and skip reason.
    """
    job_id = str(uuid.uuid4())
    criteria = config.search_criteria

    title_lower = raw_job.title.lower()
    desc_lower = raw_job.description.lower()
    combined_lower = f"{title_lower} {desc_lower}"

    # --- Hard disqualifiers ---

    # Deduplication
    if db is not None and db.exists(raw_job.external_id, raw_job.platform):
        return ScoredJob(
            id=job_id, raw=raw_job, score=0,
            pass_filter=False, skip_reason="Already applied",
        )

    # Blacklisted company
    company_lower = raw_job.company.lower()
    for blacklisted in config.company_blacklist:
        if blacklisted.lower() in company_lower:
            return ScoredJob(
                id=job_id, raw=raw_job, score=0,
                pass_filter=False,
                skip_reason=f"Blacklisted company: {blacklisted}",
            )

    # Exclude keywords
    for kw in criteria.keywords_exclude:
        if kw.lower() in combined_lower:
            return ScoredJob(
                id=job_id, raw=raw_job, score=0,
                pass_filter=False,
                skip_reason=f"Excluded keyword: {kw}",
            )

    # International searches require an explicit country in the listing. A
    # bare "Remote" does not establish work authorization or eligibility.
    target_countries = getattr(criteria, "target_countries", [])
    eligibility_note = None
    if isinstance(target_countries, list) and target_countries:
        eligible, eligibility_note = _eligibility(raw_job, criteria)
        if not eligible:
            return ScoredJob(
                id=job_id, raw=raw_job, score=0,
                pass_filter=False,
                skip_reason=eligibility_note,
            )

    # --- Executive prioritization ---
    if getattr(criteria, "executive_mode", False) is True:
        score, reasons = _score_executive(raw_job, criteria)
        threshold = config.bot.min_match_score
        passed = score >= threshold
        return ScoredJob(
            id=job_id, raw=raw_job, score=score, pass_filter=passed,
            skip_reason=None if passed else f"Score {score} below threshold {threshold}",
            eligibility_note=eligibility_note, priority_reasons=reasons,
        )

    # --- Scoring ---

    score = 0

    # Title match (0-35)
    for target_title in criteria.job_titles:
        target_lower = target_title.lower()
        if target_lower in title_lower:
            score += 35
            break
        # Partial overlap: check if any word from target is in title
        target_words = set(target_lower.split())
        title_words = set(title_lower.split())
        overlap = target_words & title_words
        if len(overlap) >= len(target_words) * 0.5:
            score += 20
            break

    # Salary match (0-20)
    if criteria.salary_min is None:
        score += 20  # No salary requirement — full points
    elif raw_job.salary is None:
        score += 10  # Unknown salary — partial credit
    else:
        salary_num = _extract_salary_number(raw_job.salary)
        if salary_num is not None and salary_num >= criteria.salary_min:
            score += 20
        elif salary_num is None:
            score += 10  # Couldn't parse — give benefit of doubt

    # Location match (0-20)
    job_location_lower = raw_job.location.lower()
    if criteria.remote_only and "remote" in job_location_lower:
        score += 20
    elif not criteria.remote_only:
        for loc in (target_countries if isinstance(target_countries, list) and target_countries else criteria.locations):
            if loc.lower() in job_location_lower:
                score += 20
                break
        else:
            # Check for same country (rough heuristic)
            if any(
                loc.lower().split(",")[-1].strip() in job_location_lower
                for loc in criteria.locations
                if "," in loc
            ):
                score += 10

    # Keyword match (0-25, +5 per keyword, max 25)
    kw_score = 0
    for kw in criteria.keywords_include:
        if kw.lower() in combined_lower:
            kw_score += 5
    score += min(kw_score, 25)

    # --- Threshold check ---
    min_score = config.bot.min_match_score
    pass_filter = score >= min_score

    skip_reason = None if pass_filter else f"Score {score} below threshold {min_score}"

    return ScoredJob(
        id=job_id, raw=raw_job, score=score,
        pass_filter=pass_filter, skip_reason=skip_reason,
        eligibility_note=eligibility_note,
    )


def _extract_salary_number(salary_str: str) -> int | None:
    """Extract an annual salary number from a salary string.

    Handles formats like "$120,000", "$120K", "$60/hr", "120000-150000".
    Returns the lower bound as an annual integer, or None if unparsable.
    """
    import re

    cleaned = salary_str.replace(",", "").replace("$", "").strip().lower()

    # Try to find numbers
    numbers = re.findall(r"[\d.]+", cleaned)
    if not numbers:
        return None

    try:
        value = float(numbers[0])
    except ValueError:
        return None

    # K suffix
    if "k" in cleaned:
        value *= 1000

    # Hourly -> annual (assume 2080 hours/year)
    if "/hr" in cleaned or "per hour" in cleaned or "hourly" in cleaned:
        value *= 2080

    return int(value)
