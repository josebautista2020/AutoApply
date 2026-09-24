"""Preview real search results and filter decisions without generating or applying.

Run from the repository: python scripts/preview_search.py --config private/config.json
The command prints JSON and opens a browser; it does not write application data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.bot import SEARCHERS  # noqa: E402
from bot.browser import BrowserManager  # noqa: E402
from config.settings import AppConfig, get_data_dir  # noqa: E402
from core.filter import score_job  # noqa: E402


def preview_jobs(config: AppConfig, page, platforms: list[str], limit: int) -> list[dict]:
    """Use the production searchers and scorer, stopping after ``limit`` jobs."""
    results: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for platform in platforms:
        for job in SEARCHERS[platform]().search(config.search_criteria, page=page):
            key = (job.platform, job.external_id)
            if key in seen:
                continue
            seen.add(key)
            scored = score_job(job, config)
            results.append({
                "platform": job.platform,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "url": job.apply_url,
                "score": scored.score,
                "review_candidate": scored.pass_filter,
                "reason": scored.skip_reason,
                "eligibility_note": scored.eligibility_note,
                "priority_reasons": scored.priority_reasons,
                "description_present": bool(job.description.strip()),
            })
            if len(results) >= limit:
                return results
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=get_data_dir() / "config.json")
    parser.add_argument("--platform", choices=sorted(SEARCHERS), action="append")
    parser.add_argument("--country", help="One country from target_countries")
    parser.add_argument("--title", help="One title from job_titles")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")
    if not args.config.is_file():
        parser.error(f"Configuration not found: {args.config}")
    try:
        config = AppConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
    except ValueError as exc:
        parser.error(f"Invalid configuration: {exc}")
    if args.country:
        if args.country not in config.search_criteria.target_countries:
            parser.error("--country must be present in target_countries")
        config.search_criteria.target_countries = [args.country]
        config.search_criteria.work_authorization = {
            key: value for key, value in config.search_criteria.work_authorization.items()
            if key == args.country
        }
    if args.title:
        if args.title not in config.search_criteria.job_titles:
            parser.error("--title must be present in job_titles")
        config.search_criteria.job_titles = [args.title]

    # Only search and score. This entry point never calls the document generator,
    # the review approval gate, an applier, or the application database.
    browser = BrowserManager(config)
    try:
        jobs = preview_jobs(
            config, browser.get_page(), args.platform or ["linkedin"], args.limit
        )
    finally:
        browser.close()
    print(json.dumps({
        "jobs": jobs,
        "count": len(jobs),
        "scope": {"countries": config.search_criteria.target_countries,
                  "titles": config.search_criteria.job_titles,
                  "platforms": args.platform or ["linkedin"]},
        "warning": "Empty results do not confirm that the portal was accessible or had no jobs"
        if not jobs else None,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
