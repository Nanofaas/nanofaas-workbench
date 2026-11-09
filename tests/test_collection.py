from pathlib import Path


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
