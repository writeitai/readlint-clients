"""Exercise the PR classifier against actual Git diffs, including renames."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci_changes.sh"


@pytest.fixture
def repository(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "README.md").write_text("docs\n")
    (tmp_path / "module.py").write_text("pass\n")
    git("add", ".")
    git("commit", "-qm", "base")
    return tmp_path, git


@pytest.mark.parametrize(
    "change,expected",
    [
        ("docs", "false"),
        ("code", "true"),
        ("workflow", "true"),
        ("unknown", "true"),
        ("rename", "true"),
    ],
)
def test_classification(repository, change, expected):
    root, git = repository
    base = git("rev-parse", "HEAD")
    if change == "rename":
        git("mv", "module.py", "README-extra.md")
    else:
        path = {
            "docs": "README.md",
            "code": "module.py",
            "workflow": ".github/workflows/ci.yml",
            "unknown": "new-file",
        }[change]
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("changed\n")
    git("add", ".")
    git("commit", "-qm", "change")
    output = root / "output"
    subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=root,
        env={
            **os.environ,
            "GITHUB_EVENT_NAME": "pull_request",
            "BASE_SHA": base,
            "HEAD_SHA": git("rev-parse", "HEAD"),
            "GITHUB_OUTPUT": str(output),
        },
        check=True,
    )
    assert output.read_text() == f"python={expected}\n"


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_main_and_manual_always_run(repository, event):
    root, _ = repository
    output = root / "output"
    subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=root,
        env={**os.environ, "GITHUB_EVENT_NAME": event, "GITHUB_OUTPUT": str(output)},
        check=True,
    )
    assert output.read_text() == "python=true\n"


def test_failed_classifier_emits_no_skip(repository):
    root, _ = repository
    output = root / "output"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=root,
        env={
            **os.environ,
            "GITHUB_EVENT_NAME": "pull_request",
            "BASE_SHA": "missing-ref",
            "HEAD_SHA": "HEAD",
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert not output.exists()
    workflow = SCRIPT.parent.parent / ".github" / "workflows" / "ci.yml"
    assert (
        "!cancelled() && needs.changes.outputs.python != 'false'"
        in workflow.read_text()
    )
