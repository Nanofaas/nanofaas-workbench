from pathlib import Path

import yaml


def test_collection_builds(built_tarball: Path):
    assert built_tarball.name == "nanofaas-workbench-0.1.0.tar.gz"


def test_installs_and_resolves_playbooks(tool, ansible_env, tmp_path: Path):
    vars_file = tmp_path / "v.json"
    vars_file.write_text('{"instances": []}')
    done = tool(
        "ansible-playbook", "--syntax-check", "-i", "localhost,",
        "-e", f"workbench_vars={vars_file}", "nanofaas.workbench.deploy",
        env=ansible_env,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr


def test_chart_default_ports_match_the_roles():
    root = Path(__file__).parents[1]
    chart = yaml.safe_load((root / "chart/values.yaml").read_text())
    main = (root / "supervisor/src/workbench_supervisor/__main__.py").read_text()
    cadvisor = (root / "roles/cadvisor/tasks/deploy.yml").read_text()
    assert chart["supervisor"]["port"] == 8099
    assert '"--port", type=int, default=8099' in main
    assert chart["cadvisor"]["port"] == 8089
    assert cadvisor.count("instance.config.port | default(8089)") == 3
