# CI/CD Debugging Breakdown — LinkedIn Thought-Sharing Post

Status: DRAFTED & ready to publish. Includes visual diagram asset.

---

## Attached Graphic Asset

![CI/CD Path Mismatch & Linter Drift Graphic](file:///C:/Users/techl/.gemini/antigravity-ide/brain/387263a4-ccb5-4cc8-a9a6-cba3b6573d8e/ci_cd_path_mismatch_diagram_1784976422371.png)

---

## The Post

```
My CI build broke on 3 Python versions simultaneously.

All 26 tests passed locally on my machine. 

So why did GitHub Actions turn red?

I dug into the logs and found two sneaky bugs hiding in plain sight:

1. Unpinned tool releases.
CI was running `pip install ruff` without a version pin. Overnight, Ruff dropped a minor update (0.16.0) with stricter default rules. My local machine was still on 0.15.17. Local green, remote red.

2. The classic Windows vs Linux slash bug.
My Python bundler generates path comments in the single-file build. 
On Windows: `extractors\geometric.py`
On Linux CI: `extractors/geometric.py`

I committed the file from Windows. The Linux runner recalculated the bundle, saw a single backslash mismatch, and flagged the bundle as "out of sync".

The fixes were surprisingly simple:

- Switched path generation to `.as_posix()` to force forward slashes everywhere.
- Ran `ruff check . --fix` to align code with updated linting rules.
- Pinned linter version ranges in `ci.yml` so new releases don't break master unexpectedly.

Matrix status: 3.11, 3.12, 3.13 all green. ✅

The takeaway?
If your build script touches file paths or installs dev tools, cross-platform normalization isn't optional. It's infrastructure.

#AIEngineering #BuildInPublic #CICD #Python #DevOps #GitHubActions
```

---

## Alternate Openers

1. "Every tests passed on my laptop. Then GitHub Actions failed on 3 runners."
2. "A single backslash broke my CI build on 3 Python versions."
3. "Two reasons my CI failed today (and neither was a test assertion)."
