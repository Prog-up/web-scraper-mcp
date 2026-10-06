"""The approved release inventory cannot waive new or fixable vulnerabilities."""

import importlib.util
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "image_release", ROOT / "scripts/check_image_release.py"
)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
POLICY = json.loads((ROOT / "deploy/release-exceptions/1.1.0.json").read_text())
NOW = datetime(2026, 10, 6, tzinfo=UTC)


def report():
    return {
        "SchemaVersion": 2,
        "ArtifactType": "container_image",
        "Results": [{"Type": "debian", "Vulnerabilities": deepcopy(POLICY["findings"])}],
    }


def check(data, policy=POLICY, now=NOW, release="1.1.0"):
    return GATE.check_report(data, release, policy, now=now)


def test_exact_approved_inventory_passes():
    blocked, accepted = check(report())
    assert not blocked
    assert len(accepted) == 60
    assert sum(row["Severity"] == "CRITICAL" for row in accepted) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("VulnerabilityID", "CVE-2099-12345"),
        ("PkgName", "new-package"),
        ("InstalledVersion", "new-version"),
        ("Severity", "CRITICAL"),
        ("FixedVersion", "fixed-version"),
    ],
)
def test_changed_or_fixable_finding_blocks(field, value):
    data = report()
    data["Results"][0]["Vulnerabilities"][0][field] = value
    blocked, accepted = check(data)
    assert len(blocked) == 1
    assert len(accepted) == 59


def test_new_result_type_blocks():
    data = report()
    data["Results"][0]["Type"] = "python-pkg"
    assert len(check(data)[0]) == 60


def test_expired_and_other_releases_are_strict():
    assert len(check(report(), now=datetime(2026, 10, 14, tzinfo=UTC))[0]) == 60
    assert len(check(report(), policy=None, release="1.1.1")[0]) == 60
    with pytest.raises(ValueError, match="match"):
        check(report(), release="1.1.1")


@pytest.mark.parametrize("mutation", ["owner", "expiry", "inventory", "duplicate", "fixed"])
def test_invalid_exception_fails_closed(mutation):
    policy = deepcopy(POLICY)
    if mutation == "owner":
        policy["owner"] = ""
    elif mutation == "expiry":
        policy["expires_at"] = "2026-10-14"
    elif mutation == "inventory":
        policy["findings"] = []
    elif mutation == "duplicate":
        policy["findings"].append(deepcopy(policy["findings"][0]))
    else:
        policy["findings"][0]["FixedVersion"] = "patched"
    with pytest.raises(ValueError):
        check(report(), policy=policy)


@pytest.mark.parametrize("data", [{}, {"Results": []}, {"SchemaVersion": 2}, None])
def test_malformed_report_fails_closed(data):
    with pytest.raises(ValueError):
        check(data)


def test_invalid_severity_fails_closed_and_clean_report_passes():
    data = report()
    data["Results"][0]["Vulnerabilities"][0]["Severity"] = "unrecognized"
    with pytest.raises(ValueError):
        check(data)
    data["Results"][0]["Vulnerabilities"] = []
    assert check(data, policy=None) == ([], [])
