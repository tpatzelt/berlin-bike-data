"""Offline structure checks for the G5 deploy files: Dockerfile, compose and CI.

`docker build`/`docker compose config` are run by hand and in CI's publish
job; these tests keep the files from drifting away from the homelab
conventions without needing a Docker daemon.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_is_pinned_non_root_and_healthchecked():
    text = (ROOT / "Dockerfile").read_text()
    for image in re.findall(r"^FROM\s+(\S+)", text, re.M):
        assert ":" in image and not image.endswith(":latest"), image
    lines = text.splitlines()
    user_idx = max(i for i, line in enumerate(lines) if line.startswith("USER "))
    run_idx = max(i for i, line in enumerate(lines) if line.startswith("RUN "))
    assert lines[user_idx].split()[1] not in ("root", "0")
    assert user_idx > run_idx
    assert "/healthz" in text and "HEALTHCHECK" in text
    assert re.search(r'^CMD .*berlinbikes.*serve', text, re.M)
    assert "COPY data/geo" in text
    assert not re.search(r"(TOKEN|PASSWORD|SECRET)\s*=", text)
    ignored = (ROOT / ".dockerignore").read_text().split()
    assert ".git" in ignored and ".bikes.env" in ignored


def test_python_version_matches_the_base_image():
    version = (ROOT / ".python-version").read_text().strip()
    assert f"python:{version}-" in (ROOT / "Dockerfile").read_text()


def test_compose_follows_homelab_conventions():
    compose = yaml.safe_load((ROOT / "deploy" / "compose.yaml").read_text())
    service = compose["services"]["bikes"]
    assert service["image"].startswith("ghcr.io/tpatzelt/berlin-bike-data:")
    assert service["restart"] == "unless-stopped"
    assert service["env_file"] == "./.env"
    assert service["volumes"] == ["/opt/dockerdata/bikes:/data"]
    assert service["environment"] == {"BIKES_DATA_DIR": "/data/parquet", "BIKES_SITE_DIR": "/data/site"}
    assert service["networks"] == ["caddy_network"]
    assert compose["networks"]["caddy_network"]["external"] is True
    assert all("ports" not in s for s in compose["services"].values())


def test_env_example_parses_and_documents_required_keys():
    keys = set()
    for line in (ROOT / "deploy" / ".bikes.env.example").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            key, sep, _ = line.partition("=")
            assert sep == "=" and re.fullmatch(r"[A-Z_]+", key), line
            keys.add(key)
    assert {"BIKES_USER_AGENT", "BIKES_DATA_DIR", "BIKES_OPERATOR_NAME"} <= keys


def test_workflow_tests_then_publishes_both_tags():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["push"]["branches"] == ["master"] and "pull_request" in triggers
    jobs = workflow["jobs"]
    assert any(step.get("run") == "uv run pytest -q" for step in jobs["test"]["steps"])
    assert jobs["publish"]["needs"] == "test"
    assert jobs["publish"]["permissions"]["packages"] == "write"
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "ghcr.io/tpatzelt/berlin-bike-data:latest" in text
    assert "ghcr.io/tpatzelt/berlin-bike-data:sha-" in text
    assert set(re.findall(r"secrets\.(\w+)", text)) == {"GITHUB_TOKEN"}
