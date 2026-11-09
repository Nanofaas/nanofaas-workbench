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
