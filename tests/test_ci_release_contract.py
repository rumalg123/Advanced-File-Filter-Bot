"""PH-008: lightweight release-process safety contract.

Verifies repository-level defaults without GitHub API access or secrets.
Does NOT replace GitHub administrator-enforced branch protection.
"""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_actions_are_sha_pinned_and_not_privileged_on_pull_request():
    workflow = (ROOT / ".github/workflows/python-tests.yml").read_text()
    action_references = re.findall(r"^\s*uses:\s*(\S+)", workflow, re.MULTILINE)
    assert action_references, "Expected at least one official GitHub Action"
    assert all(re.search(r"@[0-9a-f]{40}$", ref) for ref in action_references)
    assert "pull_request_target:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "name: pytest" in workflow
    assert "name: container-preflight" in workflow
    assert "branches: [main]" in workflow
    assert "--cov-report=xml:coverage.xml" in workflow
    assert "TEST_MONGO_URI: mongodb://127.0.0.1:27017" in workflow
    assert "TEST_REDIS_STATE_URI: redis://127.0.0.1:6380/0" in workflow


def test_ci_validates_image_without_publishing_or_deploying():
    workflow = (ROOT / ".github/workflows/python-tests.yml").read_text()
    commands = [
        line.strip()
        for line in workflow.splitlines()
        if line.strip().startswith((
            "run: ", "docker ", "kubectl ", "helm ",
        ))
    ]
    actual = "\n".join(commands)
    assert "docker build --tag file-filter-bot:ci ." in actual
    assert "docker push" not in actual
    assert "kubectl " not in actual
    assert "helm " not in actual
    assert "docker compose --profile protected-state config --quiet" in workflow


def test_default_deployment_flags_are_opt_in_and_runtime_is_nonroot():
    compose = (ROOT / "docker-compose.yml").read_text()
    dockerfile = (ROOT / "Dockerfile").read_text()
    settings = (ROOT / "config/settings.py").read_text()
    assert "AUTO_UPDATE=${AUTO_UPDATE:-false}" in compose
    assert "UPDATE_ON_START=${UPDATE_ON_START:-false}" in compose
    assert "REDIS_STATE_URI=${REDIS_STATE_URI:-}" in compose
    assert 'durable_indexing: bool = Field(' in settings
    assert "default=False" in settings
    assert "USER botuser" in dockerfile


def test_release_policy_requires_staging_and_both_successful_checks():
    runbook = (ROOT / "docs/CI_CD_RELEASE_GATES.md").read_text()
    template = (ROOT / ".github/PULL_REQUEST_TEMPLATE.md").read_text()
    assert "pytest" in runbook
    assert "container-preflight" in runbook
    assert "staging" in template.lower()
    assert "rollback" in template.lower()
    assert "Do not deploy or merge Draft PR #4 automatically" in template
