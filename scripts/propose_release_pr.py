#!/usr/bin/env python3
"""Propose a release PR with a suggested version bump and AI-generated notes.

This script is intended to run after changes have been merged to `main`.
It computes a conservative suggested semver bump from commits since the last
tag, generates release notes using `generate_release_notes_ai.py`, creates a
branch `release/vX.Y.Z` with the bumped `pyproject.toml` and `RELEASE_NOTES_vX.Y.Z.md`,
pushes the branch and opens a draft PR for maintainer review.

Requirements:
- `git` must be available and repository must be up-to-date.
- `gh` (GitHub CLI) is required to open the PR. If not present, the script
  will print the commands to run manually.

This script intentionally does NOT create tags or publish to PyPI; it
creates a PR for maintainers to review and merge when happy.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# Global dry-run flag set in main()
DRY_RUN = False


def run(cmd: Iterable[str], capture: bool = False) -> str:
    """Run a command unless we're in DRY_RUN mode (then just print it).

    If capture is True we always execute and return output.
    """
    cmd_list = list(cmd)
    if capture:
        return subprocess.check_output(cmd_list, stderr=subprocess.DEVNULL).decode().strip()

    if DRY_RUN:
        print("[DRY RUN] ", shlex.join(cmd_list))
        return ""

    subprocess.check_call(cmd_list)
    return ""


def get_latest_tag() -> Optional[str]:
    try:
        return run(["git", "describe", "--tags", "--abbrev=0"], capture=True)
    except subprocess.CalledProcessError:
        return None


def get_commits_since(tag: Optional[str]) -> List[Tuple[str, str, str]]:
    # Use the same separators as generate_release_notes_ai.py: unit sep (\x1f) and record sep (\x1e)
    rng = f"{tag}..HEAD" if tag else "HEAD"
    fmt = "%H%x1f%s%x1f%b%x1e"
    try:
        out = subprocess.check_output(["git", "log", rng, f"--pretty=format:{fmt}"], stderr=subprocess.DEVNULL).decode(errors="ignore")
    except subprocess.CalledProcessError:
        return []

    commits = []
    for entry in out.split("\x1e"):
        if not entry.strip():
            continue
        parts = entry.split("\x1f")
        sha = parts[0].strip() if len(parts) > 0 else ""
        subj = parts[1].strip() if len(parts) > 1 else ""
        body = parts[2].strip() if len(parts) > 2 else ""
        commits.append((sha, subj, body))
    return commits


def suggest_bump(commits: List[Tuple[str, str, str]], current_version: str) -> str:
    """Conservative semver suggestion.

    Heuristic:
    - major: any commit subject or body contains 'BREAKING CHANGE' or subject matches a conventional '!'
    - minor: any subject contains 'feat' as a type
    - patch: otherwise
    """
    major_re = re.compile(r"BREAKING CHANGE|!:", re.IGNORECASE)
    feat_re = re.compile(r"^feat(\(|:)|\bfeat\b", re.IGNORECASE)

    is_major = False
    is_minor = False
    for _, subj, body in commits:
        if subject_contains_major(subj) or subject_contains_major(body):
            is_major = True
            break
        if feat_re.search(subj) or feat_re.search(body):
            is_minor = True

    major, minor, patch = parse_semver(current_version)
    if is_major:
        major += 1
        minor = 0
        patch = 0
    elif is_minor:
        minor += 1
        patch = 0
    else:
        patch += 1

    return f"{major}.{minor}.{patch}"


def is_release_style_commit(subject: str) -> bool:
    """Return True if the commit subject looks like a release/bump/proposal commit."""
    if not subject:
        return False
    patterns = [
        r"^release[:/\s]",
        r"^chore\(release\):",
        r"^bump[:\s]",
        r"^release/",
        r"^release:\s",
        r"^release-",
        r"^chore\(?bump\)?[:\s]",
    ]
    for p in patterns:
        if re.search(p, subject, flags=re.IGNORECASE):
            return True
    return False


def subject_contains_major(text: str) -> bool:
    if not text:
        return False
    if "BREAKING CHANGE" in text:
        return True
    # conventional commit '!' after type, e.g. feat!: description
    if re.search(r"^[^:!]+!", text):
        return True
    return False


def parse_semver(v: str) -> Tuple[int, int, int]:
    parts = v.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        major, minor, patch = 0, 0, 0
    return major, minor, patch


def bump_pyproject_version(new_version: str) -> None:
    p = Path("pyproject.toml")
    if not p.exists():
        raise FileNotFoundError("pyproject.toml not found")
    text = p.read_text(encoding="utf-8")
    # naive replace of project.version = "x.y.z"
    pattern = re.compile(r'(version\s*=\s*\")([^\"]+)(\")')
    def _repl(m: re.Match) -> str:
        return f"{m.group(1)}{new_version}{m.group(3)}"

    new_text, n = pattern.subn(_repl, text, count=1)
    if n == 0:
        # fallback: try to find [project] and add/replace
        raise RuntimeError("Failed to update version in pyproject.toml")
    p.write_text(new_text, encoding="utf-8")


def write_notes_file(version: str, body: str) -> Path:
    fname = Path(f"RELEASE_NOTES_v{version}.md")
    fname.write_text(body, encoding="utf-8")
    return fname


def generate_notes(version: str, rng: Optional[str]) -> str:
    cmd = [sys.executable, "scripts/generate_release_notes_ai.py", "--version", version]
    if rng:
        cmd += ["--range", rng]
    # We capture output by letting the script write the file and then reading it
    subprocess.check_call(cmd)
    fname = Path(f"RELEASE_NOTES_v{version}.md")
    if not fname.exists():
        raise RuntimeError("generate_release_notes_ai.py failed to produce notes file")
    return fname.read_text(encoding="utf-8")


def branch_exists(remote: str, branch: str) -> bool:
    try:
        out = subprocess.check_output(["git", "ls-remote", "--heads", remote, branch], stderr=subprocess.DEVNULL).decode().strip()
        return bool(out)
    except subprocess.CalledProcessError:
        return False


def local_branch_exists(branch: str) -> bool:
    try:
        subprocess.check_output(["git", "rev-parse", "--verify", branch], stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def create_branch_with_changes(branch: str, new_version: str, notes_path: Path) -> None:
    # Create branch, update pyproject, add notes, commit
    run(["git", "checkout", "-b", branch])
    if DRY_RUN:
        print(f"[DRY RUN] would update pyproject.toml to {new_version} and add {notes_path}")
        return
    bump_pyproject_version(new_version)
    run(["git", "add", "pyproject.toml", str(notes_path)])
    run(["git", "commit", "-m", f"chore(release): propose v{new_version}"])


def push_branch(branch: str) -> None:
    run(["git", "push", "-u", "origin", branch])
    if DRY_RUN:
        print(f"[DRY RUN] would push branch {branch} to origin")


def open_pr(branch: str, version: str, notes_path: Path) -> None:
    # Use gh to create a draft PR
    body_file = str(notes_path)
    if DRY_RUN:
        print(f"[DRY RUN] would create a draft PR for branch {branch} with title 'Release: v{version}' and body from {body_file}")
        return

    try:
        run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", f"Release: v{version}", "--body-file", body_file, "--draft"])
    except FileNotFoundError:
        print("gh CLI not found. To create the PR manually, run:")
        print(f"  git push -u origin {branch}")
        print(f"  gh pr create --base main --head {branch} --title 'Release: v{version}' --body-file {body_file} --draft")


def read_current_version() -> str:
    import tomllib

    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    os.chdir(repo_root)

    global DRY_RUN
    parser = argparse.ArgumentParser(description="Propose a release PR with suggested version bump and generated notes")
    parser.add_argument("--dry-run", action="store_true", help="Do not create branches/commits/pushes or open PRs; just print intended actions")
    args = parser.parse_args()
    DRY_RUN = args.dry_run

    latest_tag = get_latest_tag()
    commits = get_commits_since(latest_tag)

    if not commits:
        print("No commits since last tag; nothing to propose.")
        return 0

    # Filter out release-style commits (these include the proposal commit itself)
    non_release_commits = [(s, subj, body) for (s, subj, body) in commits if not is_release_style_commit(subj)]

    if not non_release_commits:
        print("No non-release commits since last tag; nothing to propose (guard engaged).")
        return 0

    current_version = read_current_version()
    suggested = suggest_bump(non_release_commits, current_version)

    branch = f"release/v{suggested}"
    remote = "origin"
    if branch_exists(remote, branch):
        print(f"Branch {branch} already exists on {remote}; aborting to avoid duplicate PRs.")
        return 0
    if local_branch_exists(branch):
        print(f"Local branch {branch} already exists; aborting to avoid duplicate work.")
        return 0

    rng = f"{latest_tag}..HEAD" if latest_tag else "HEAD"
    notes = generate_notes(suggested, rng)
    notes_path = write_notes_file(suggested, notes)

    create_branch_with_changes(branch, suggested, notes_path)
    push_branch(branch)
    open_pr(branch, suggested, notes_path)

    print(f"Proposed release PR created for v{suggested} (branch: {branch}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
