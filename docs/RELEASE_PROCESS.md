
# Release Process

This document describes the recommended release workflow for the **queuack** project. It preserves a human review step for release notes while automating repetitive tasks (note generation and optional publishing) via GitHub Actions.

---

## High-Level Flow

1. **Merge** changes to `main`.
2. **Bump** the package version in `pyproject.toml` (or run `make bump`).
3. **Generate release notes** (AI-assisted) and create an annotated tag using the generated notes.
4. **Push** the annotated tag to `origin` — the CI pipeline will run and create a *draft* GitHub Release containing the generated notes and upload the notes as an artifact for review.
5. **Review and edit** the draft release on GitHub. When ready, publish the release (manually) or re-run the release workflow with `publish=true` to also build/publish to PyPI.

---

## Important Files & Workflows

- `scripts/generate_release_notes_ai.py` — generates `RELEASE_NOTES_vX.Y.Z.md` using OpenAI (falls back to `git log` if the key is missing or the AI call fails).

   Note: the generator excludes release-style commits (e.g. "release:", "bump:") from the summarized input by default to avoid noisy notes. Use `--include-release-commits` when generating locally if you want those included.

- `scripts/propose_release_pr.py` — optional helper that runs after merges to `main` to propose a Release PR. It:
   - suggests a conservative semver bump using commit heuristics;
   - generates AI-assisted release notes;
   - opens a draft PR with the bumped `pyproject.toml` and `RELEASE_NOTES_vX.Y.Z.md` for maintainers to review and merge.

   This keeps the bump decision in human hands while automating the tedious parts. The GitHub Actions workflow `propose_release_pr.yml` can run this script on `push` to `main` or manually via workflow dispatch.
   
   NOTE: for safety the CI workflow currently runs the proposer in `--dry-run` mode (it prints the intended actions but does not create branches/commits/pushes or open PRs). To enable automated branch/PR creation in CI remove the `--dry-run` flag from `.github/workflows/propose_release_pr.yml` or run `scripts/propose_release_pr.py` locally without `--dry-run`.
- **Makefile targets:**
  - `make gen-release-notes` — run the generator locally.
  - `make bump v=patch|minor|major` — bump version, commit, and create an annotated tag.
- `.github/workflows/release.yml` — CI workflow that:
  - runs on tag pushes (`v*`) and supports manual dispatch;
  - generates release notes, uploads them as an artifact, and creates a **draft** GitHub Release;
  - optionally publishes to PyPI when run manually with `publish=true` and `PYPI_API_TOKEN` is set.

---

## Required Repository Secrets

- `OPENAI_API_KEY` — (recommended) used by the CI generator to produce polished drafts.
- `PYPI_API_TOKEN` — optional; required if you want CI to publish to PyPI.

---

## Local Release Steps (Recommended Manual Flow)

1. **Merge** your release branch into `main`.

2. **Bump the version locally** (choose one):

   ```bash
   # Manual: edit pyproject.toml then commit
   git add pyproject.toml
   git commit -m "release: vX.Y.Z"

   # Or use Makefile helper
   make bump v=patch   # or v=minor / v=major
   ```

3. **Generate release notes locally and review them.** You can use the AI helper (requires `OPENAI_API_KEY` in your environment) or fallback to `git log`:

   ```bash
   # Generate using OpenAI (writes RELEASE_NOTES_vX.Y.Z.md)
   make gen-release-notes

   # Or run directly
   python3 scripts/generate_release_notes_ai.py --version X.Y.Z --range vA.B.C..HEAD
   ```

4. **Create an annotated tag** that uses the generated notes as the tag annotation:

   ```bash
   # Annotate the tag with the file content
   git tag -a vX.Y.Z -F RELEASE_NOTES_vX.Y.Z.md

   # Push the tag to origin (this will trigger the CI to create a draft release)
   git push origin refs/tags/vX.Y.Z
   ```

5. **Review the draft release on GitHub.** Actions will create a draft release and upload the `RELEASE_NOTES_vX.Y.Z.md` as an artifact. Edit the draft release title/body as needed.

6. **When you're ready to publish the release and optionally publish to PyPI:**

   - **Manual publish via GitHub UI:** open the draft release and click **Publish release**.
   - **Or run the workflow dispatch with `publish=true`** to let CI build and push to PyPI (requires `PYPI_API_TOKEN` secret):

     ```bash
     gh workflow run release.yml --ref main --field publish=true
     ```

---

## Notes About the CI Behavior

- The workflow will create a **draft** release so maintainers have a chance to review/edit notes before publishing. The generated notes are uploaded as an artifact so you can download and inspect them if you prefer not to publish a draft right away.
- The `publish` job only runs when the workflow is manually dispatched with `publish=true` and `PYPI_API_TOKEN` is present as a secret — this prevents accidental package uploads.

---

## Security and Privacy Considerations

- The AI generator sends commit messages and limited context to OpenAI for summarization. Only enable `OPENAI_API_KEY` for repositories where that is acceptable.
- Secrets are not exposed to workflows triggered by PRs from forks; only tag pushes/dispatches from the repository will have access to secrets.

---

## Rollback & Tag Hygiene

- If you need to change a tag's annotation before pushing, update the annotated tag locally and force-push the tag:

   ```bash
   git tag -f -a vX.Y.Z -F RELEASE_NOTES_vX.Y.Z.md <commit>
   git push --force origin refs/tags/vX.Y.Z
   ```

- If a remote tag was overwritten, collaborators should refresh their local tags:

   ```bash
   git fetch --prune origin
   git tag -d vX.Y.Z
   git fetch origin tag vX.Y.Z
   ```

---

## Troubleshooting

- If the CI failed to generate notes because `OPENAI_API_KEY` was missing, the workflow will produce a `git log` fallback draft. You can always run `make gen-release-notes` locally and upload the file if you prefer a human-only flow.
- If PyPI publishing fails, check that `PYPI_API_TOKEN` is set and has appropriate permissions.

---

## FAQ

**Q: Why drafts instead of auto-publish?**  
A: Drafts allow manual inspection of notes and final edits. Publishing packages to PyPI is irreversible and should be gated by human approval.

**Q: Can we fully automate releases?**  
A: Yes — remove the draft step and set `publish=true` on dispatch or set `PYPI_API_TOKEN` and push annotated tags. However, keep in mind the increased risk of publishing accidental or low-quality notes.

---

## Contact & Ownership

Release process maintained by the repository owners. For changes to the workflow, open a PR proposing the edits and tag the maintainers for review.

---

*This document was generated to match the new CI-assisted release flow (AI note drafts + draft releases). If you'd like a more strict/automated flow (JSON structured notes, validations, or automatic changelog merging), I can add those features next.*
