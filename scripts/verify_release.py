#!/usr/bin/env python3
"""Verify release/tag consistency for the repository.

Checks that the version in pyproject.toml either matches the most recent
git tag (v{version}) or that a release-style commit is present in the
range since the last tag. This is useful as a pre-merge or CI gate to
prevent version drift between file metadata and git tags.

Exit codes:
  0 - verification succeeded
  2 - verification failed (mismatch and no release commit)

Usage: python3 scripts/verify_release.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def read_pyproject_version(pyproject_path: Path) -> str:
    import tomllib

    data = tomllib.load(pyproject_path.open("rb"))
    return data["project"]["version"]


def get_latest_tag() -> str | None:
    try:
        out = subprocess.check_output(["git", "describe", "--tags", "--abbrev=0"], stderr=subprocess.DEVNULL)
        return out.decode().strip()
    except subprocess.CalledProcessError:
        return None


def get_commit_subjects(since_tag: str | None) -> list[str]:
    rng = f"{since_tag}..HEAD" if since_tag else "HEAD"
    out = subprocess.check_output(["git", "log", rng, "--pretty=format:%s"]).decode()
    return [line.strip() for line in out.splitlines() if line.strip()]


def has_release_commit(subjects: list[str]) -> bool:
    # Common release patterns: release:, chore(release):, bump: or release/<version>
    patterns = [
        r"^release[:/\s]",
        r"^chore\(release\):",
        r"^bump[:\s]",
        r"^release/",
        r"^release:\s",
        r"^release-",
    ]
    for s in subjects:
        for p in patterns:
            if re.search(p, s, flags=re.IGNORECASE):
                return True
    return False


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        print("pyproject.toml not found", file=sys.stderr)
        return 2

    version = read_pyproject_version(pyproject)
    latest_tag = get_latest_tag()

    if latest_tag and latest_tag.startswith("v") and latest_tag[1:] == version:
        print(f"OK: pyproject version {version} matches tag {latest_tag}")
        return 0

    subjects = get_commit_subjects(latest_tag)

    if has_release_commit(subjects):
        print(
            f"OK: pyproject version {version} does not match latest tag {latest_tag}, but a release-style commit exists in the range"
        )
        return 0

    print(
        "ERROR: pyproject version does not match the latest git tag and no release-style commit was found.\n"
        f"pyproject version: {version}\nlatest tag: {latest_tag}\n"
        "Either create a tag `v{version}` or include a release commit (e.g. 'release: vX.Y.Z' or 'chore(release): ...').",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
