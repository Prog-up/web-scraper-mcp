"""Fail closed on OSV matches for every registry package in the frozen uv lockfile."""

import json
import sys
import tomllib
import urllib.request
from pathlib import Path


def main() -> int:
    packages = [
        p
        for p in tomllib.loads(Path("uv.lock").read_text())["package"]
        if p.get("source", {}).get("registry")
    ]
    queries = [
        {"package": {"name": p["name"], "ecosystem": "PyPI"}, "version": p["version"]}
        for p in packages
    ]
    request = urllib.request.Request(
        "https://api.osv.dev/v1/querybatch",
        data=json.dumps({"queries": queries}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS API
        result = json.load(response)
    results = result["results"]
    if len(results) != len(packages):
        raise ValueError("incomplete OSV audit response")
    affected = 0
    for package, findings in zip(packages, results, strict=True):
        if findings.get("vulns"):
            affected += 1
            ids = ", ".join(v["id"] for v in findings["vulns"])
            print(f"{package['name']} {package['version']}: {ids}")
    print(f"Queried {len(packages)} packages; {affected} affected packages")
    return 1 if affected else 0


if __name__ == "__main__":
    sys.exit(main())
