"""A private search update preserves the installed resume and other profile data."""

import json
from pathlib import Path

from scripts.update_search_profile import update_search_profile


def test_update_search_profile_keeps_installed_resume_and_backs_up(tmp_path):
    installed = {
        "profile": {
            "first_name": "Jane", "last_name": "Doe", "email": "jane@example.com",
            "phone": "5550100", "city": "Bogota", "state": "", "bio": "Architect",
            "fallback_resume_path": "C:/Users/Jane/.autoapply/default_resume.pdf",
        },
        "search_criteria": {
            "job_titles": ["Director of Engineering"], "locations": ["Remote"],
            "target_countries": ["Colombia"],
            "work_authorization": {"Colombia": "unknown"},
        },
        "bot": {"apply_mode": "auto", "schedule": {"enabled": True}},
    }
    incoming = {
        "profile": {"first_name": "Other", "last_name": "Person", "email": "other@example.com",
                    "phone": "123", "city": "Elsewhere", "state": "", "bio": "Other"},
        "search_criteria": {
            "job_titles": ["Director of Engineering", "Director de Ingeniería"],
            "locations": ["Remote"], "target_countries": ["Colombia", "United States"],
            "work_authorization": {"Colombia": "authorized",
                                   "United States": "needs_sponsorship"},
            "executive_mode": True,
        },
    }
    target = tmp_path / "config.json"
    source = tmp_path / "incoming.json"
    target.write_text(json.dumps(installed), encoding="utf-8")
    source.write_text(json.dumps(incoming), encoding="utf-8")

    result = update_search_profile(source, target)
    actual = json.loads(target.read_text(encoding="utf-8"))

    assert result["status"] == "updated"
    assert json.loads(Path(result["backup"]).read_text(encoding="utf-8")) == installed
    assert actual["profile"]["first_name"] == "Jane"
    assert actual["profile"]["fallback_resume_path"] == installed["profile"]["fallback_resume_path"]
    assert actual["search_criteria"]["job_titles"] == incoming["search_criteria"]["job_titles"]
    assert actual["search_criteria"]["work_authorization"]["Colombia"] == "authorized"
    assert actual["bot"]["apply_mode"] == "review"
    assert actual["bot"]["schedule"]["enabled"] is False
