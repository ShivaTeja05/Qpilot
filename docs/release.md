# Releasing qPilot

A release is two files, a **wheel** (`qpilot-X.Y.Z-py3-none-any.whl`, what `pip` installs, about 3 MB) and an **sdist** (`qpilot-X.Y.Z.tar.gz`, the sources it is built from), published to **PyPI** and attached to a **GitHub Release**. Everything is done by `.github/workflows/release.yml` when a tag `vX.Y.Z` is pushed. The workflow is **inert until you set it up once** (section 1): until then a tag builds, checks and creates the GitHub Release, and the PyPI job is skipped. Nothing here publishes anything by itself, logs in anywhere or pushes a tag.

For users: [install.md](install.md).

## 1. One-time setup

PyPI uses **Trusted Publishing**: PyPI is told "this GitHub repository, this workflow, this environment may upload this project", so there is no API token to create, store or leak.

1. **Check the name.** On 28 October 2026 `https://pypi.org/project/qpilot/` did not exist (404), so the name was free. Names can be taken at any time; look again before you rely on it. If it is gone, change `name` in `pyproject.toml` (the command and the import stay `qpilot`).
2. **PyPI account** with two-factor sign-in. Open <https://pypi.org/manage/account/publishing/> and **add a new pending publisher** (the project does not exist yet, so the first upload creates it):
   * PyPI project name: `qpilot`
   * Owner: `ShivaTeja05`, repository: `Qpilot` (the repository that runs the workflow)
   * Workflow filename: `release.yml`
   * Environment name: `pypi`
3. **GitHub environment.** Repository Settings, Environments, New environment `pypi`. Recommended: tick **Required reviewers** and add yourself, so a tag waits for one click before anything reaches PyPI, and under **Deployment branches and tags** choose *Selected branches and tags* with the tag rule `v*`, so only a version tag can publish. Protect the tags too (Settings, Rules, a tag ruleset on `v*`: only maintainers create them), since anyone who can push a `v*` tag starts a release.
4. **Switch it on.** Settings, Secrets and variables, Actions, **Variables**, New repository variable: `PYPI_PUBLISH` = `true`. (Without it the PyPI job is skipped. Remove it to stop publishing.)
5. **Rehearsal, optional but wise.** A version number on PyPI can never be used twice, even after deleting the files. Do steps 2 and 3 again on <https://test.pypi.org/manage/account/publishing/> with the environment name `testpypi`, then Actions, release, **Run workflow**, `publish_to` = `testpypi`. It builds, checks, smoke-tests on three systems and uploads to TestPyPI. Install the result with `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple qpilot`.

## 2. Making a release

1. On `main`, everything green (the `ci` workflow: lint, tests on three systems, package, installed wheel, audit, frontend).
2. Write the entry in `CHANGELOG.md`.
3. Set the version in **two places**, the same string: `__version__` in `qpilot/__init__.py` (the wheel, `qpilot --version`, every record and report read it from there) and `version:` in `CITATION.cff`. `scripts/check_dist.py` fails the build if they or the tag disagree.
4. If `frontend/` changed, `cd frontend && npm run build` and commit `qpilot/web/static` (the release job rebuilds it and fails if the committed page differs).
5. Commit, push, wait for green, then tag **that commit**:
   ```bash
   git tag -a v0.2.0 -m "qPilot 0.2.0"
   git push origin v0.2.0
   ```
6. Watch Actions, release. In order: **the committed page** (identical to what its source builds; the only job that runs npm), **build and check** (`python -m build`; `twine check --strict`; `scripts/check_dist.py`: contents, sizes, versions, tag) then **installed wheel** on Ubuntu, macOS and Windows (`scripts/smoke_installed.py --full`: console scripts, the page and its guarded API, an `.xlsx`, and Studio's end-to-end checks on the pinned demo, 28 today) then, in parallel, **GitHub Release** (both files, generated notes) and **publish to PyPI** (waits for your approval if you set reviewers).
7. Verify like a user, on a clean machine or folder: `pipx install qpilot==0.2.0` (or `uv tool install qpilot==0.2.0`), `qpilot --version`, `qpilot doctor`.

If a job fails before PyPI, fix, delete the tag (`git push origin :refs/tags/v0.2.0`, `git tag -d v0.2.0`), and tag again. If PyPI already has the files, the number is spent: fix forward with the next version, and **yank** the bad one on PyPI (Manage, Options, Yank) so installers skip it.

## 3. Doing the same by hand

All of this runs without GitHub and publishes nothing:

```bash
python -m pip install build twine
python -m build                                  # dist/qpilot-X.Y.Z.tar.gz and -py3-none-any.whl
twine check --strict dist/*
python scripts/check_dist.py dist --tag vX.Y.Z   # contents, sizes, versions
python -m venv /tmp/qp && /tmp/qp/bin/pip install "dist/qpilot-X.Y.Z-py3-none-any.whl[studio,sim]"
cd /tmp && /tmp/qp/bin/python /path/to/clone/scripts/smoke_installed.py --full
```

(Windows: `Scripts\python.exe` instead of `bin/python`.) The last line runs from a folder that is not the clone, with nothing of the clone on the path: that is the point.

## 4. What is in the wheel, and what is not

| In | Why |
|---|---|
| `qpilot/` with the prebuilt page (`web/static`), the Curve Judge model, the HGNC symbol list, the MIQE items, the vendored `rdmlpython` and its RDML schemas | everything the program reads at run time |
| `qpilot/_packs/` (from `packs/`) | the Run Gate rule packs: `gate_rules.PACKS_DIR_CANDIDATES` looks here first |
| `qpilot/_methods/` (from `methods/`) | the method cards the page and the reports cite as `methods/<name>.md`; nothing reads them, they are for people |
| `qsim/` (from `sim/src/qsim`) | the Decision Simulator the Audit, the MCP server and `qpilot app --audit` use; installed with qPilot, so the `sim` extra only keeps old install lines working |
| **Not**: `sim/data`, `sim/results` (6 MB of validation corpora) | `qsim validate` and `qsim external` score against them and need a clone; they say so instead of failing |
| **Not**: tests, fixtures, `frontend/`, `training/`, `validation/`, `research_notes/`, demo videos | not needed to run; the sdist leaves them out too |

The **sdist** is an allow-list (`[tool.hatch.build.targets.sdist] include` in `pyproject.toml`): enough to build the wheel and to read what it was built from. If a packager wants the tests, add `/tests` there (about 8 MB with the fixtures). `scripts/check_dist.py` caps both files at 6 MB and any single member at 1 MB, so an accidentally added data file fails CI.

`qsim` is a top-level module name in the wheel. The PyPI project called `qsim` (Google's quantum simulator) is an unrelated, empty meta-package, so nothing collides on disk, but rename the module (it is imported in about 40 files) if that ever changes.

## 5. Keeping the pieces in step

* **ruff 0.17.1** is written in three places: `RUFF_VERSION` in `.github/workflows/ci.yml`, `rev:` in `.pre-commit-config.yaml`, and the version in your virtual environment. Change them together; the pre-commit and the CI run must agree or one of them reports what the other does not.
* **Dependabot** watches pip, npm (`/frontend`) and GitHub Actions weekly, grouped. An npm update changes the build of the page, so its pull request also needs `npm run build` committed (`ci` says so with a diff). The pre-commit hook revisions are not watched by Dependabot.
* **Node** is only for building the page (`>= 22`, see `frontend/package.json`); installing or releasing needs it only for the "page equals source" check.
* **Windows in CI.** The Windows jobs in `ci.yml` (`test` and `smoke`) carry `continue-on-error`, because Windows is new there: they show red or green on every run without blocking a merge. After the first green run, delete the `continue-on-error` lines so Windows blocks like the others. `release.yml` never allows a Windows failure.
* **Python versions.** `requires-python = ">=3.11"`; CI covers 3.11, 3.12 (all three systems) and 3.13 (Linux). A new Python (3.14) is one more line in the matrix and one classifier.
