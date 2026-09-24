"""Private profile installation must preserve existing user files."""

import json
from pathlib import Path

import pytest

from config.settings import AppConfig
from scripts.import_profile import install_profile


def _inputs(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    config = source / "config.json"
    config.write_text(json.dumps({
        "profile": {
            "first_name": "Jane", "last_name": "Doe", "email": "jane@example.com",
            "phone": "5550100", "city": "Bogota", "state": "", "country": "Colombia",
            "bio": "Architect", "screening_answers": {},
        },
        "search_criteria": {
            "job_titles": ["Director of Engineering"], "locations": ["Colombia"],
            "target_countries": ["Colombia"], "executive_mode": True,
        },
        "bot": {"apply_mode": "full_auto", "schedule": {"enabled": True}},
    }), encoding="utf-8")
    resume = source / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nexample")
    experience = source / "experience.md"
    experience.write_text("## Professional Experience\n- Led a team.\n", encoding="utf-8")
    return config, resume, experience


def test_install_sets_local_resume_and_review_mode(tmp_path):
    inputs = _inputs(tmp_path)
    target = tmp_path / "data"
    result = install_profile(*inputs, target)
    saved = AppConfig.model_validate_json((target / "config.json").read_text())
    assert result["status"] == "installed"
    assert saved.profile.fallback_resume_path == str((target / "default_resume.pdf").resolve())
    assert saved.bot.apply_mode == "review"
    assert not saved.bot.schedule.enabled
    assert saved.search_criteria.executive_mode
    assert (target / "profile" / "experiences" / "imported_experience.txt").read_text() == inputs[2].read_text()


def test_existing_profile_requires_replace_and_is_backed_up(tmp_path):
    inputs = _inputs(tmp_path)
    target = tmp_path / "data"
    target.mkdir()
    (target / "config.json").write_text("old config", encoding="utf-8")
    with pytest.raises(FileExistsError):
        install_profile(*inputs, target)
    assert (target / "config.json").read_text() == "old config"
    result = install_profile(*inputs, target, replace=True)
    backup = Path(result["backup_dir"])
    assert (backup / "config.json").read_text() == "old config"
    assert (target / "config.json").read_text() != "old config"


def test_dry_run_does_not_create_data_directory(tmp_path):
    inputs = _inputs(tmp_path)
    target = tmp_path / "data"
    assert install_profile(*inputs, target, dry_run=True)["status"] == "validated"
    assert not target.exists()


def test_invalid_resume_has_no_side_effects(tmp_path):
    inputs = _inputs(tmp_path)
    inputs[1].write_bytes(b"not a PDF")
    target = tmp_path / "data"
    with pytest.raises(ValueError, match="PDF"):
        install_profile(*inputs, target)
    assert not target.exists()
