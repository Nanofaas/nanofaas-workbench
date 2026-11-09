# CLAUDE.md

The Ansible collection `nanofaas.workbench` (roles under `roles/`, playbooks
`deploy`/`collect`/`undeploy` under `playbooks/`) plus the `supervisor/` Python
project, the only custom code. Host vars format: `docs/vars.md`.

## Setup

```bash
uv sync --all-groups
```

Run Ansible only through `uv run` (ansible-core is pinned to 2.20 in the dev
group; a system Ansible may be another version).

## Commands

```bash
uv run pytest -q                       # docker/kind tests skip without the tool
uv run pytest -q --cov -m "not kind"   # CI `checks` job; supervisor coverage >= fail_under
uv run pytest -q -m kind tests/integration/test_pod_form.py   # CI `kind` job
uv run ruff check . && uv run ruff format --check .
uv run basedpyright
uv run ansible-lint
uv run pre-commit run --all-files      # everything CI runs
```

`galaxy.yml` `version` equals the release tag without `v`.
Releases: pushing a tag `v<version>` runs `.github/workflows/release.yml`
(tag == `galaxy.yml` version == the supervisor default image tag == chart version, then the
multi-arch image to ghcr.io and a GitHub Release with the tarball). Bump
`galaxy.yml`, `roles/supervisor/defaults/main.yml` and `chart/Chart.yaml`
(`version`, `appVersion`) together; the release workflow checks all four.
