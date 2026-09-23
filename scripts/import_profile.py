"""Install a private AutoApply profile without adding personal files to Git.

Run from the repository: python scripts/import_profile.py --config ... --resume ...
--experience ... [--replace]. Use --dry-run to validate inputs without writes.
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

from config.settings import AppConfig  # noqa: E402


def _atomic_copy(source: Path, destination: Path) -> None:
    """Copy a file to the destination directory, then replace atomically."""
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
        staged = Path(tmp.name)
    try:
        shutil.copyfile(source, staged)
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


def _atomic_text(content: str, destination: Path) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=destination.parent, delete=False
    ) as tmp:
        staged = Path(tmp.name)
        tmp.write(content)
    try:
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


def install_profile(
    config_path: Path,
    resume_path: Path,
    experience_path: Path,
    data_dir: Path,
    *,
    replace: bool = False,
    dry_run: bool = False,
) -> dict[str, str]:
    """Validate private inputs, then install them with a backup before replacement."""
    for source in (config_path, resume_path, experience_path):
        if not source.is_file():
            raise ValueError(f"File not found: {source}")
    if resume_path.suffix.lower() != ".pdf" or not resume_path.read_bytes().startswith(b"%PDF-"):
        raise ValueError("Resume must be a PDF file")
    experience = experience_path.read_text(encoding="utf-8")
    if not experience.strip():
        raise ValueError("Experience file is empty")

    data = json.loads(config_path.read_text(encoding="utf-8"))
    config = AppConfig.model_validate(data)
    # Importing a profile must never turn on unattended applications.
    config.bot.apply_mode = "review"
    config.bot.schedule.enabled = False

    resume_dest = data_dir / "default_resume.pdf"
    exp_dest = data_dir / "profile" / "experiences" / "imported_experience.txt"
    config_dest = data_dir / "config.json"
    destinations = (resume_dest, exp_dest, config_dest)
    existing = [path for path in destinations if path.exists()]
    if existing and not replace:
        raise FileExistsError(
            "Existing AutoApply files found; pass --replace to back them up and replace them"
        )
    if dry_run:
        return {"status": "validated", "data_dir": str(data_dir), "existing": str(len(existing))}

    backup_dir = None
    if existing:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_dir = data_dir / "backups" / f"profile-import-{stamp}"
        for original in existing:
            backup = backup_dir / original.relative_to(data_dir)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, backup)

    resume_dest.parent.mkdir(parents=True, exist_ok=True)
    exp_dest.parent.mkdir(parents=True, exist_ok=True)
    config.profile.fallback_resume_path = str(resume_dest.resolve())
    _atomic_copy(resume_path, resume_dest)
    _atomic_text(experience, exp_dest)
    _atomic_text(config.model_dump_json(indent=2) + "\n", config_dest)
    return {
        "status": "installed",
        "data_dir": str(data_dir),
        "backup_dir": str(backup_dir) if backup_dir else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--resume", type=Path, required=True)
    parser.add_argument("--experience", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".autoapply")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = install_profile(
            args.config, args.resume, args.experience, args.data_dir,
            replace=args.replace, dry_run=args.dry_run,
        )
    except (ValueError, FileExistsError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Import failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
