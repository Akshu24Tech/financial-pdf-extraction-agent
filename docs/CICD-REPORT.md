# CI/CD — Detailed Learning Report

A hands-on CI/CD pipeline built from scratch on this repo
(`financial-pdf-extraction-agent`), once the PDF-extraction work saturated at
golden 180/180. The repo became a teaching vehicle: build a real
continuous-integration + continuous-delivery pipeline and learn the mechanics
by shipping it, one numbered "level" at a time.

**Final outcome:** a public Python package — `akshu-finagent 0.2.0`, live on
PyPI (`pip install akshu-finagent`) — released by pushing a single git tag,
fully behind a branch-protection gate. Every change went through
branch → PR → green checks → merge, including the docs.

- **Period:** 2026-06-17 → 2026-06-19
- **Stack:** GitHub Actions, branch protection, PyPI/TestPyPI trusted publishing (OIDC)
- **Companion record:** `WORKLOG.md` → "CI/CD learning track" (same history with commit/PR references)

---

## 1. The mental model

**CI (Continuous Integration)** — on every push/PR a robot checks out the code,
installs deps, lints, and tests. Catch breakage immediately, on every change.

**CD (Continuous Delivery/Deployment)** — once tests pass, automatically build
and ship the artifact (a wheel, a GitHub Release, a PyPI upload).

They chain: **CI proves the code is good → CD ships that good code.** You can't
sensibly automate shipping until integration is trustworthy.

Everything runs on GitHub's servers (`ubuntu-latest`), defined as YAML in
`.github/workflows/`. Key vocabulary:

| Term | Meaning |
|------|---------|
| trigger (`on:`) | WHEN a workflow runs (`push`, `pull_request`, `push: tags`) |
| job | a fresh, isolated machine |
| step | one action (`uses:` a prebuilt action) or shell command (`run:`) |
| `needs:` | declares order/dependency between jobs |
| matrix | run the same job many times with different inputs, in parallel |
| environment | a named deploy target; carries protection rules + OIDC identity |

---

## 2. The levels (what was built, in order)

### Level 3 — Basic CI (foundation)
Runs on every push + PR: install deps → `ruff` lint → `pytest`. Plus a fix to
add the project root to the pytest import path, and a README status badge.

### Level 4 — Branch protection (CI becomes a real GATE)
Before this, CI showed red/green but nothing stopped a red merge. Set a
branch-protection rule on `main` **via `gh api`** (command line, not the
website):
1. No pushing straight to `main` — everything goes through a PR.
2. A PR can't merge unless the required status check is green.

### Level 5 — Matrix + caching + the gate job (PR #2)
```yaml
strategy:
  fail-fast: false
  matrix:
    python-version: ["3.11", "3.12", "3.13"]
```
- **Matrix:** test job runs 3× in parallel, one per Python version.
- **`fail-fast: false`:** one version failing still runs the rest → see ALL failures.
- **`cache: pip`:** reuse downloaded packages between runs → free speed-up.
- **`all-green` gate job:** the fix for the gotcha in §3.

### Level 6 — CD / deploy stage
- **6.1 (PR #3):** made the project pip-installable — added
  `[build-system]`/`[project]` to `pyproject.toml`; proved `python -m build`.
- **6.2 (PR #4):** tag-triggered `release.yml` — build wheel + sdist, publish a
  GitHub Release with artifacts + auto-generated notes. First end-to-end CD.
- **6.3 (PR #5):** publish to TestPyPI via OIDC trusted publishing (no secrets).
- **6.4 (PRs #8/#9):** publish to **real PyPI**. Restructured into
  build-once/publish-many; renamed the distribution; dropped TestPyPI after a
  collision. `akshu-finagent 0.2.0` went live.

---

## 3. The gotchas (where the real learning was)

Every level taught something by breaking first. These are the transferable
lessons.

### Gotcha 1 — A green check is just a SIGNAL, not enforcement (L4)
CI running does NOT protect `main`. By default you can still merge red code.
Only **branch protection that requires the check** turns a signal into a gate.

### Gotcha 2 — A matrix RENAMES your status checks (L5)
Adding a matrix renamed the check from `test` to `test (3.11)`, `test (3.12)`,
`test (3.13)`. The Level-4 rule required a check named `test` — which no longer
existed — so it would block **every** PR forever.

**Fix — a stable gate job:**
```yaml
all-green:
  if: always()          # report even if the matrix failed
  needs: [test]         # wait for all matrix jobs
  runs-on: ubuntu-latest
  steps:
    - run: |
        if [ "${{ needs.test.result }}" != "success" ]; then
          echo "One or more matrix jobs failed."; exit 1
        fi
```
Require `all-green` in branch protection — never the volatile per-version
checks. **Principle:** point the protection rule at ONE stable gate; decouple
the contract from the implementation. `if: always()` matters — without it a
skipped gate can be misread as passing.

### Gotcha 3 — A build can succeed and still ship a broken package (L6.1)
First wheel built fine but silently DROPPED the `finagent.extractors`
subpackage (`packages = ["finagent"]` only shipped the top level). **Always
inspect what's inside the wheel.** Fix: auto-discovery
`[tool.setuptools.packages.find]` `include = ["finagent*"]`; verify with
`twine check dist/*`.

### Gotcha 4 — `invalid-publisher` is a registration mismatch, never a code bug (L6.3)
First TestPyPI publish failed: `invalid-publisher: valid token, but no
corresponding publisher`. The OIDC token minted fine and reached TestPyPI —
PyPI matches the token's CLAIMS against the registered publisher
**field-by-field**, and one field didn't match. Cause: PyPI's "Workflow name"
field wants the **filename** (`release.yml`), not the workflow's `name:`
(`Release`). Fix the registration, then `gh run rerun <id> --failed` (no new
tag needed). Bonus: a failed publish does NOT consume the version.

### Gotcha 5 — "Available" (404) does NOT mean "allowed" (L6.4)
`pypi.org/pypi/finagent/json` returned 404 (unclaimed), but registering it was
rejected: **"too similar to an existing project."** PyPI has a typosquat guard
ON TOP of the exact-name check. Renamed the **distribution** to
`akshu-finagent` — a one-line `[project].name` change, because the
**distribution name and import name are allowed to differ** (`import finagent`
unchanged; cf. `scikit-learn` → `import sklearn`).

### Gotcha 6 — Two trusted publishers with identical claims COLLIDE (L6.4)
Tried to publish to TestPyPI + PyPI both. PyPI worked; TestPyPI failed with
`400 Non-user identities cannot create new projects`. The old `finagent`
TestPyPI project (from 6.3) had a trusted publisher with IDENTICAL OIDC claims
(owner/repo/`release.yml`/`testpypi`); the token matched the wrong one and
refused to create `akshu-finagent` through it. Dropped the TestPyPI job — the
sandbox had served its purpose.

### Gotcha 7 — Environment approval gates are plan-gated on private repos (post-6.4)
Tried to add a required-reviewer approval rule on the `pypi` environment via
`gh api`. GitHub rejected it: *"ensure the billing plan supports the required
reviewers protection rule."* Environment protection rules are **free only on
PUBLIC repos**; a private repo needs GitHub Pro. Skipped it. (Alternative
without paying: a `workflow_dispatch` manual-trigger publish — the manual click
IS the approval.)

---

## 4. Core concepts that crystallised

- **CI vs CD** — integration (test every change) vs delivery (ship good changes).
- **Signal vs gate** — a check protects nothing until branch protection requires it.
- **Infra as commands** — set branch protection / environments via `gh api`, not
  clicks. Reproducible and reviewable; itself a core CI/CD skill.
- **Separate workflows by trigger** — CI runs always (`push`/`pull_request`);
  release runs rarely (`push: tags`). Different files, different purposes.
- **Build once, publish many** — one `build` job uploads the wheel+sdist as an
  artifact; publish jobs download that SAME artifact. The bits you tested are
  the bits you ship, everywhere.
- **OIDC trusted publishing** — short-lived token instead of a stored API token;
  nothing to leak or rotate. Registration claims must match field-by-field.
- **Least privilege** — grant each job only the permissions it needs
  (`id-token: write` for publishing, `contents: write` for a Release, nothing
  for CI). Limits blast radius.
- **Distribution name ≠ import name** — the PyPI name and the `import` name are
  independent.
- **Immutability** — published index versions can't be reused or overwritten
  (only yanked); bump the version to retry/re-release.

---

## 5. The final pipeline

Two workflow files.

**`ci.yml`** — runs on every push + PR:
- matrix test across Python 3.11/3.12/3.13 (`fail-fast: false`), `cache: pip`,
  `ruff` + `pytest`
- `all-green` gate job (`if: always()`, `needs: [test]`) — the single required
  check in branch protection

**`release.yml`** — runs only on a `v*` tag:
```
build            -> build wheel + sdist once, upload as artifact
publish-pypi     -> download artifact, OIDC publish to real PyPI (env: pypi, id-token: write)
github-release   -> download artifact, create GitHub Release (contents: write)
```

**To ship a release:**
```bash
git tag v0.2.0 && git push origin v0.2.0
```
One tag → build → PyPI → GitHub Release.

**Guardrails in force:** branch protection on `main` (PR required, `all-green`
must pass); `.gitattributes` normalises line endings.

---

## 6. Status & what's left

**Complete.** Levels 3 → 6.4 shipped; `akshu-finagent 0.2.0` live on PyPI; full
CI → CD pipeline behind a gate.

Optional, not blocking:
- Bump action versions to clear the **Node 20** deprecation warning
  (action-version maintenance is part of owning a pipeline).
- Approval gate — only viable if the repo goes public or the plan upgrades
  (see Gotcha 7); or use a `workflow_dispatch` manual publish instead.
