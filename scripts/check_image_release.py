"""Fail closed on HIGH/CRITICAL findings except an owned, expiring release inventory."""

import argparse
import json
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

FIELDS = ("Type", "VulnerabilityID", "PkgName", "InstalledVersion", "Severity")
SEVERITIES = {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}


def finding_key(row: dict) -> tuple[str, ...]:
    if any(not isinstance(row.get(field), str) or not row[field].strip() for field in FIELDS):
        raise ValueError("Finding must identify type, CVE, package, version and severity")
    if row["Severity"] not in SEVERITIES:
        raise ValueError("Unrecognized finding severity")
    return tuple(row[field] for field in FIELDS)


def check_report(
    report: dict, release: str, exception: dict | None = None, *, now: datetime | None = None
) -> tuple[list[dict], list[dict]]:
    """Return blocked and accepted findings; invalid inputs raise ValueError."""
    if (
        not isinstance(report, dict)
        or report.get("SchemaVersion") != 2
        or report.get("ArtifactType") != "container_image"
        or not isinstance(report.get("Results"), list)
        or not report["Results"]
    ):
        raise ValueError("Expected a complete Trivy v2 container image report")
    allowed = set()
    if exception is not None:
        if not isinstance(exception, dict) or exception.get("release") != release:
            raise ValueError("Exception must match this release")
        for field in ("owner", "reason", "expires_at"):
            if not isinstance(exception.get(field), str) or not exception[field].strip():
                raise ValueError(f"Exception requires {field}")
        expiry = datetime.fromisoformat(exception["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("Exception expiry must have a timezone")
        rows = exception.get("findings")
        if not isinstance(rows, list) or not rows:
            raise ValueError("Exception requires an exact finding inventory")
        for row in rows:
            if not isinstance(row, dict) or row.get("FixedVersion"):
                raise ValueError("Only unfixed findings may be excepted")
            key = finding_key(row)
            if key[-1] not in {"HIGH", "CRITICAL"} or key in allowed:
                raise ValueError("Exception inventory must contain distinct HIGH/CRITICAL findings")
            allowed.add(key)
        if (now or datetime.now(UTC)) >= expiry:
            allowed.clear()
    blocked, accepted = [], []
    for result in report["Results"]:
        if not isinstance(result, dict) or not isinstance(result.get("Type"), str):
            raise ValueError("Invalid Trivy result")
        rows = result.get("Vulnerabilities", [])
        if not isinstance(rows, list):
            raise ValueError("Invalid vulnerability list")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid vulnerability")
            finding = row | {"Type": result["Type"]}
            key = finding_key(finding)
            if key[-1] not in {"HIGH", "CRITICAL"}:
                continue
            fixed = row.get("FixedVersion")
            if fixed is not None and not isinstance(fixed, str):
                raise ValueError("Invalid fixed version")
            if key in allowed and not fixed:
                accepted.append(finding)
            else:
                blocked.append(finding)
    return blocked, accepted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--release")
    parser.add_argument("--exception-dir", type=Path, default=Path("deploy/release-exceptions"))
    args = parser.parse_args()
    try:
        release = (
            args.release or tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
        )
        release = release.removeprefix("v")
        # Never turn arbitrary version text into a filesystem path.
        if len(release.split(".")) != 3 or not all(part.isdecimal() for part in release.split(".")):
            raise ValueError("Release must be a stable semantic version")
        exception_path = args.exception_dir / f"{release}.json"
        exception = json.loads(exception_path.read_text()) if exception_path.exists() else None
        blocked, accepted = check_report(json.loads(args.report.read_text()), release, exception)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Image release gate failed: {exc}", file=sys.stderr)
        return 1
    print(f"Release {release}: {len(accepted)} approved unfixed findings; {len(blocked)} blocked")
    for row in blocked:
        print("BLOCKED:", *finding_key(row), "fixed:", row.get("FixedVersion") or "unavailable")
    return int(bool(blocked))


if __name__ == "__main__":
    raise SystemExit(main())
