"""Update private search criteria while retaining the locally installed CV and profile.

Run: python scripts/update_search_profile.py --source path/to/config.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import AppConfig, get_data_dir  # noqa: E402


def update_search_profile(source: Path, target: Path) -> dict:
    """Validate and back up the installed config before a scoped search update."""
    incoming = AppConfig.model_validate_json(source.read_text(encoding="utf-8"))
    installed = AppConfig.model_validate_json(target.read_text(encoding="utf-8"))

    installed.search_criteria.job_titles = incoming.search_criteria.job_titles
    installed.search_criteria.target_countries = incoming.search_criteria.target_countries
    installed.search_criteria.work_authorization = incoming.search_criteria.work_authorization
    installed.search_criteria.executive_mode = incoming.search_criteria.executive_mode
    installed.bot.apply_mode = "review"
    installed.bot.schedule.enabled = False
    # Validate the combined configuration before writing any local files.
    validated = AppConfig.model_validate(installed.model_dump())

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = target.parent / "backups" / f"config-before-search-update-{stamp}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, delete=False
    ) as tmp:
        staged = Path(tmp.name)
        tmp.write(validated.model_dump_json(indent=2) + "\n")
    try:
        os.replace(staged, target)
    finally:
        staged.unlink(missing_ok=True)
    return {
        "status": "updated",
        "backup": str(backup),
        "titles": validated.search_criteria.job_titles,
        "work_authorization": validated.search_criteria.work_authorization,
        "apply_mode": validated.bot.apply_mode,
        "schedule_enabled": validated.bot.schedule.enabled,
        "fallback_resume_preserved": bool(validated.profile.fallback_resume_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=get_data_dir())
    args = parser.parse_args()
    target = args.data_dir / "config.json"
    if not args.source.is_file() or not target.is_file():
        parser.error("Both --source and the installed config.json must exist")
    try:
        result = update_search_profile(args.source, target)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Search update failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
