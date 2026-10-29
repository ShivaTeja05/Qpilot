"""Red team (excellence round): the CI and release workflows (``.github/workflows``).

What the release publishes must be built from the tagged sources by a job that runs nothing
else's code, and no workflow may hand a pull request's code a write token or let text an
outsider chooses (a branch name, a title) into a shell command:

* every workflow starts read-only (``permissions: contents: read``), and only the job that
  makes the GitHub Release may write contents, only the publishing jobs (each behind an
  environment, PyPI's Trusted Publishing) may ask for an OIDC token;
* no ``pull_request_target`` / ``workflow_run`` trigger (they run with the base repository's
  token beside a pull request's code);
* no ``${{ github.event.* }}``, ``github.head_ref``, ``inputs.*`` or ``env.*`` set from them
  inside a ``run:`` script (script injection); values reach scripts through ``env:``;
* RT-EX-009: the job that builds the wheel and the sdist (whose ``dist`` artifact is published)
  ran ``npm ci``, so any npm package's install script could change ``qpilot/`` before
  ``python -m build``; the page check is now a job of its own, and the build job runs no npm;
* every checkout in the release workflow sets ``persist-credentials: false`` (no token is left
  in ``.git/config`` for later steps);
* RT-EX-013: every action is pinned by its full commit SHA with the release it is as a
  ``# vX.Y.Z`` comment (a moved tag of a compromised action never runs, in the publishing job
  least of all), and Dependabot keeps the pins current (it updates the SHA and the comment).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).parents[2] / ".github" / "workflows"
NAMES = ("ci.yml", "release.yml")
UNTRUSTED = re.compile(
    r"\$\{\{\s*(github\.event\.|github\.head_ref|inputs\.|github\.event_name\s*==\s*'pull)"
)


def _load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads the key `on` as true
    return data


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return list(job.get("steps") or [])


@pytest.mark.parametrize("name", NAMES)
def test_every_workflow_starts_read_only(name):
    assert _load(name)["permissions"] == {"contents": "read"}


@pytest.mark.parametrize("name", NAMES)
def test_no_trigger_runs_untrusted_code_with_the_bases_token(name):
    triggers = _load(name)["on"]
    keys = set(triggers) if isinstance(triggers, dict) else set(triggers or [])
    assert not keys & {"pull_request_target", "workflow_run", "issue_comment"}, keys


@pytest.mark.parametrize("name", NAMES)
def test_no_outsider_text_is_spliced_into_a_script(name):
    for job_name, job in _load(name)["jobs"].items():
        for step in _steps(job):
            script = str(step.get("run") or "")
            assert not UNTRUSTED.search(script), (job_name, step.get("name"), script[:120])


def test_only_the_release_job_writes_and_only_publishers_get_a_token():
    for name in NAMES:
        for job_name, job in _load(name)["jobs"].items():
            perms = job.get("permissions") or {}
            if perms.get("contents") == "write":
                assert (name, job_name) == ("release.yml", "github-release"), job_name
            if perms.get("id-token") == "write":
                assert name == "release.yml" and job.get("environment"), job_name
                assert [s.get("uses", "") for s in _steps(job)][-1].startswith(
                    "pypa/gh-action-pypi-publish@"
                ), job_name
            assert set(perms) <= {"contents", "id-token"}, (job_name, perms)


def test_the_published_files_are_built_by_a_job_that_runs_no_npm():
    jobs = _load("release.yml")["jobs"]
    builders = [
        n
        for n, job in jobs.items()
        if any(
            s.get("uses", "").startswith("actions/upload-artifact@")
            and (s.get("with") or {}).get("name") == "dist"
            for s in _steps(job)
        )
    ]
    assert builders == ["build"], builders
    build = jobs["build"]
    scripts = " ".join(str(s.get("run") or "") for s in _steps(build))
    uses = [s.get("uses", "") for s in _steps(build)]
    assert "python -m build" in scripts
    assert "npm" not in scripts and not any(u.startswith("actions/setup-node@") for u in uses)
    page = jobs.get("page")
    assert page is not None and "page" in (build.get("needs") or []), build.get("needs")
    assert "git diff --exit-code -- ../qpilot/web/static" in " ".join(
        str(s.get("run") or "") for s in _steps(page)
    )
    for publisher in ("github-release", "pypi", "testpypi"):
        assert "smoke" in jobs[publisher]["needs"] and "build" in jobs[publisher]["needs"]


def test_release_checkouts_leave_no_token_behind():
    for job_name, job in _load("release.yml")["jobs"].items():
        for step in _steps(job):
            if step.get("uses", "").startswith("actions/checkout@"):
                assert (step.get("with") or {}).get("persist-credentials") is False, job_name


def test_pypi_is_published_only_from_a_tag_and_can_be_switched_off():
    job = _load("release.yml")["jobs"]["pypi"]
    assert "github.ref_type == 'tag'" in job["if"] and "vars.PYPI_PUBLISH != 'false'" in job["if"]
    assert job["environment"]["name"] == "pypi"


# RT-EX-013
PINNED = re.compile(r"^\s*-?\s*uses:\s*([\w.-]+/[\w./-]+)@([0-9a-f]{40}) # (v\d+\.\d+\.\d+)\s*$")


@pytest.mark.parametrize("name", NAMES)
def test_every_action_is_pinned_by_commit_with_its_release(name):
    lines = (WORKFLOWS / name).read_text(encoding="utf-8").splitlines()
    uses = [line for line in lines if re.match(r"^\s*-?\s*uses:", line)]
    assert uses, name
    unpinned = [line.strip() for line in uses if not PINNED.match(line)]
    assert not unpinned, unpinned
    steps = [s for job in _load(name)["jobs"].values() for s in _steps(job) if "uses" in s]
    assert len(steps) == len(uses)  # every step's action is on a line of its own, as checked


def test_dependabot_keeps_the_pinned_actions_current():
    config = yaml.safe_load((WORKFLOWS.parent / "dependabot.yml").read_text(encoding="utf-8"))
    ecosystems = {u["package-ecosystem"]: u for u in config["updates"]}
    assert ecosystems["github-actions"]["directory"] == "/"
