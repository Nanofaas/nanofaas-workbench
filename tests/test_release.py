import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_supervisor_default_image_tag_is_the_collection_version():
    version = yaml.safe_load((ROOT / "galaxy.yml").read_text())["version"]
    image = yaml.safe_load((ROOT / "roles/supervisor/defaults/main.yml").read_text())[
        "supervisor_image"
    ]
    assert image == f"ghcr.io/nanofaas/workbench-supervisor:{version}"


def test_release_workflow_has_the_guard_image_and_release_jobs():
    text = (ROOT / ".github/workflows/release.yml").read_text()
    wf = yaml.safe_load(text)
    assert wf[True]["push"]["tags"] == ["v*"]  # PyYAML reads `on` as True
    assert set(wf["jobs"]) == {"verify", "image", "release"}
    assert wf["jobs"]["image"]["needs"] == "verify"
    assert wf["jobs"]["image"]["permissions"]["packages"] == "write"
    assert wf["jobs"]["release"]["needs"] == ["verify", "image"]
    verify = "\n".join(s.get("run", "") for s in wf["jobs"]["verify"]["steps"])
    assert "galaxy.yml" in verify
    assert "roles/supervisor/defaults/main.yml" in verify
    assert "GITHUB_REF_NAME" in verify


def test_release_workflow_permissions_digest_platforms_and_tarball():
    text = (ROOT / ".github/workflows/release.yml").read_text()
    jobs = yaml.safe_load(text)["jobs"]
    assert jobs["release"]["permissions"]["contents"] == "write"
    assert jobs["image"]["permissions"]["packages"] == "write"
    build = next(s for s in jobs["image"]["steps"] if s.get("id") == "push")
    assert set(build["with"]["platforms"].split(",")) == {
        "linux/amd64",
        "linux/arm64",
    }
    assert jobs["image"]["outputs"]["digest"] == "${{ steps.push.outputs.digest }}"
    steps = jobs["release"]["steps"]
    publish = next(s for s in steps if "gh release" in s.get("run", ""))
    assert publish["env"]["DIGEST"] == "${{ needs.image.outputs.digest }}"
    assert "$DIGEST" in publish["run"]
    assert "nanofaas-workbench-$VERSION.tar.gz" in publish["run"]
    assert any("ansible-galaxy collection build" in s.get("run", "") for s in steps)


def test_chart_version_is_the_collection_version():
    version = yaml.safe_load((ROOT / "galaxy.yml").read_text())["version"]
    chart = yaml.safe_load((ROOT / "chart/Chart.yaml").read_text())
    assert chart["version"] == version
    assert chart["appVersion"] == version
    jobs = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]
    verify = "\n".join(s.get("run", "") for s in jobs["verify"]["steps"])
    assert "chart/Chart.yaml" in verify
    assert "appVersion" in verify


def test_every_action_is_pinned_by_commit_sha():
    for name in ("ci.yml", "release.yml"):
        jobs = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())["jobs"]
        for job in jobs.values():
            for step in job["steps"]:
                if "uses" in step:
                    ref = step["uses"].split("@")[1]
                    assert re.fullmatch(r"[0-9a-f]{40}", ref), (name, step["uses"])


def test_ci_smoke_tests_the_consumer_install_path():
    steps = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"][
        "checks"
    ]["steps"]
    run = "\n".join(s.get("run", "") for s in steps)
    assert 'ansible-galaxy collection install "git+file://' in run
    assert "ansible_collections/nanofaas/workbench/playbooks" in run
    assert '"$pb/deploy.yml"' in run
