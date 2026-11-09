# nanofaas-workbench

The Ansible collection `nanofaas.workbench`: experiment-platform components
(Prometheus, Loki, fluent-bit, k6, node_exporter, cAdvisor, a supervisor) as
roles, deployable as containers or Helm pods.

```bash
ansible-galaxy collection install git+https://github.com/Nanofaas/nanofaas-workbench.git,v0.1.0
ansible-playbook -i <inventory> -e workbench_vars=<file> nanofaas.workbench.deploy
```

The vars file format is in [docs/vars.md](docs/vars.md).
