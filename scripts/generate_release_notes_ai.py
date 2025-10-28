#!/usr/bin/env python3
"""Generate a draft RELEASE_NOTES_vX.Y.Z.md using OpenAI from git commits.

Usage: python3 scripts/generate_release_notes_ai.py [--version X.Y.Z] [--range vA.B.C..HEAD]

Notes:
- By default the generator excludes release-style commits (e.g. "release:", "bump:")
    from the summarized input to avoid noisy/duplicate entries in the generated notes.
    Use `--include-release-commits` to override and include them.

If OPENAI_API_KEY is not present, falls back to a plain git-log draft.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from typing import Optional

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"


def read_version_from_pyproject() -> str:
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def run_git(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()


def last_tag() -> Optional[str]:
    try:
        return run_git(["git", "describe", "--tags", "--abbrev=0"])
    except Exception:
        return None


def collect_commits(range_spec: Optional[str]) -> str:
    """Collect commits for the given range and return a single string.

    This uses a binary-safe delimiter to separate commits so we can reliably
    parse subject/body and filter release-style commits. The caller can then
    pass the cleaned commit_text to the AI prompt. If range_spec is omitted,
    we default to <last_tag>..HEAD when a tag exists, otherwise HEAD.
    """

    if range_spec:
        rng = range_spec
    else:
        lt = last_tag()
        if lt:
            rng = f"{lt}..HEAD"
        else:
            rng = "HEAD"

    # Use a reliable delimiter to separate commits: %x1f (unit separator) between
    # fields and %x1e (record separator) between commits.
    fmt = "%h%x1f%s%x1f%b%x1e"
    cmd = ["git", "log", rng, f"--pretty=format:{fmt}"]

    try:
        out = subprocess.check_output(cmd).decode(errors="ignore")
    except subprocess.CalledProcessError:
        out = ""
    return out


def parse_and_filter_commits(raw: str, exclude_release_commits: bool = True) -> str:
    """Parse raw git log (with our delimiters) and optionally exclude release commits.

    Returns a human-readable commit block suitable for the release notes prompt.
    """
    if not raw:
        return ""

    commits = []

    # Patterns used to detect release-style commits (same family as verify_release.py)
    release_patterns = [
        r"^release[:/\s]",
        r"^chore\(release\):",
        r"^bump[:\s]",
        r"^release/",
        r"^release:\s",
        r"^release-",
    ]

    for entry in raw.split("\x1e"):
        if not entry.strip():
            continue
        parts = entry.split("\x1f")
        # Expect: [sha, subject, body]
        sha = parts[0].strip() if len(parts) > 0 else ""
        subject = parts[1].strip() if len(parts) > 1 else ""
        body = parts[2].strip() if len(parts) > 2 else ""

        # Decide whether to include this commit
        if exclude_release_commits and subject:
            skip = False
            for p in release_patterns:
                if re.search(p, subject, flags=re.IGNORECASE):
                    skip = True
                    break
            if skip:
                continue

        # Recompose a readable commit representation
        if body:
            commit_text = f"{sha} {subject}\n\n{body}"
        else:
            commit_text = f"{sha} {subject}"
        commits.append(commit_text)

    return "\n\n".join(commits)


def build_prompt(version: str, commit_text: str) -> str:
    """Construct a strict prompt that instructs the model to always produce useful output.

    The model is required to:
    - Produce markdown only (no extra annotations or explanations).
    - Include sections: Highlights, Added, Changed, Fixed, Breaking Changes.
    - Always include at the end a 'Raw commits' section listing each commit as '- <sha> <summary>'.
    - NEVER invent features; only summarize the provided commits.
    - If there are no commits, still produce a short 'No notable changes' markdown with the Raw commits section empty.
    """

    instructions = (
        "You are a strict release-notes generator.\n"
        f"Write release notes in Markdown for version {version}.\n"
        "REQUIREMENTS:\n"
        "- Output MUST be valid Markdown only (no surrounding code fences).\n"
        "- Include these headings in this order: Highlights, Added, Changed, Fixed, Breaking Changes, Raw commits.\n"
        "- Under 'Raw commits' list each commit on its own line as: '- <sha> <commit summary>'.\n"
        "- Do not invent any changes that are not present in the commits. If unsure, omit the claim.\n"
        "- Keep bullets concise (one short sentence each).\n\n"
    )

    return instructions + "\nCOMMITS TO SUMMARIZE:\n\n" + commit_text + "\n\nProduce only the markdown body for the release notes."


def call_openai(prompt: str, model: str, max_tokens: int, key: str) -> Optional[str]:
    # Use urllib to avoid extra dependencies
    import urllib.request

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a strict, concise release-notes generator. Follow instructions exactly."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        # Use low temperature to avoid creative hallucinations
        "temperature": 0.0,
    }

    data = json.dumps(payload).encode()
    req = urllib.request.Request(API_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_data = resp.read().decode()
            js = json.loads(resp_data)
            # Chat completions response: choose first message content
            choices = js.get("choices") or []
            if len(choices) > 0:
                message = choices[0].get("message", {})
                return message.get("content")
            # Some endpoints may return different shapes; try `output_text`
            return js.get("output_text")
    except Exception as e:
        print(f"OpenAI API error: {e}", file=sys.stderr)
        return None


def write_notes(version: str, body: str) -> str:
    fname = f"RELEASE_NOTES_v{version}.md"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(body)
    return fname


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", help="Version string (X.Y.Z). If omitted read from pyproject.toml")
    parser.add_argument("--range", help="git range to summarize, e.g. v0.1.1..HEAD")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI model to use")
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--dry-run", action="store_true", help="Print AI output but don't write file")
    parser.add_argument("--fail-on-ai-error", action="store_true", help="Exit non-zero if AI call fails")
    parser.add_argument(
        "--include-release-commits",
        action="store_true",
        help="Include release-style commits (e.g. 'release:', 'bump:') in the summary. By default these are excluded to avoid noisy generated notes.",
    )

    args = parser.parse_args(argv)

    version = args.version or read_version_from_pyproject()
    raw = collect_commits(args.range)
    # By default we exclude release-style commits which tend to pollute AI summaries
    commits = parse_and_filter_commits(raw, exclude_release_commits=not args.include_release_commits)

    if not commits.strip():
        commits = "(no commits found in range)"

    api_key = os.environ.get("OPENAI_API_KEY")

    if api_key:
        prompt = build_prompt(version, commits)
        print("Calling OpenAI to generate release notes (this may consume tokens)...")
        ai_resp = call_openai(prompt, args.model, args.max_tokens, api_key)
        if ai_resp and len(ai_resp.strip()) > 80 and "Raw commits" in ai_resp:
            body = ai_resp
        else:
            print("AI response was insufficient or failed to include required sections; falling back to git-log draft.", file=sys.stderr)
            if args.fail_on_ai_error:
                return 2
            # Build a simple, deterministic markdown draft from commits
            body = [f"# Release Notes for Version {version}", "", "## Raw commits", ""]
            for line in commits.splitlines():
                s = line.strip()
                if not s:
                    continue
                # try to split sha and rest
                parts = s.split(maxsplit=1)
                if len(parts) == 2:
                    body.append(f"- {parts[0]} {parts[1]}")
                else:
                    body.append(f"- {s}")
            body = "\n".join(body)
    else:
        print("OPENAI_API_KEY not set; using git-log fallback.")
        body = "# Release notes (git-log fallback)\n\n" + commits

    if args.dry_run:
        print("--- DRY RUN OUTPUT ---")
        print(body)
        return 0

    fname = write_notes(version, body)
    print(f"Wrote {fname}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
