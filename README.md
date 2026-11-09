# nanofaas-workbench

The Ansible collection `nanofaas.workbench`: the experiment-platform components
as roles, deployable as Docker containers or as Helm pods. One vars file
describes the instances; three playbooks act on it. Only the supervisor is
custom code (`supervisor/`, image `ghcr.io/nanofaas/workbench-supervisor`).

## Components

| Component | What it is | Container form | Pod form |
| --- | --- | --- | --- |
| `node-exporter` | host metrics | bridge, published port | Pod on a node |
| `cadvisor` | container metrics | bridge, published port | Pod on a node |
| `loki` | log store | bridge, published port | Deployment |
| `log-collector` | fluent-bit shipping logs to Loki | host network | Deployment |
| `prometheus` | metrics store, scrapes the exporters | host network | Deployment |
| `loadgen` | k6 job replaying a schedule | host network, runs once | Job |
| `supervisor` | watches targets, reports `healthy`/`degraded`/`fault` | host network | Deployment |

Details, config keys and pinned images are in each role's `README.md`.

## Run forms

`form: container` (default) runs `wb-<instance>` through the Docker SDK on the
target; `form: pod` installs the collection's Helm chart as release
`wb-<instance>` (needs `helm` 3 and a kubeconfig on the target). See
`roles/common/README.md`.

## Vars file

A JSON file passed as `-e workbench_vars=<path>`: a list of
`{name, component, form, cpuset, config}` plus an optional `collect_dir`. The
format and its validation rules are in [docs/vars.md](docs/vars.md).

## By hand

```bash
ansible-galaxy collection install git+https://github.com/Nanofaas/nanofaas-workbench.git,v0.1.0
ansible-playbook -i localhost, -e workbench_vars=vars.json nanofaas.workbench.deploy
ansible-playbook -i localhost, -e workbench_vars=vars.json nanofaas.workbench.collect
ansible-playbook -i localhost, -e workbench_vars=vars.json nanofaas.workbench.undeploy
```

`deploy` starts the instances; `collect` writes snapshots and metrics under
`collect_dir/<instance>/` (Prometheus snapshot, fluent-bit metrics, remote Loki
data and loadgen output); `undeploy` removes everything labelled with the
instance. `localhost` and `127.0.0.1` run in place; any other inventory host
goes over its own connection. Collection dependencies (`community.docker`,
`kubernetes.core`) are pinned in `galaxy.yml`.

## Supervisor API

Targets are `scrape_up`, `container_running`, `swap_quiet` or `http_ok`; the
supervisor only signals, it never stops anything.

- `PUT /targets/<name>` add or replace (204, 400 when invalid); `DELETE` removes (204).
- `GET /status` the state, per-target status and anomalies; a `fault` is sticky until the target is removed.
- `GET /metrics` Prometheus text for the state and each target.

Target parameters and semantics: `roles/supervisor/README.md`.

## Docker Desktop

Host-network containers share the Linux VM's network, not the Mac's, so
`localhost` ports of `prometheus`, `log-collector`, `supervisor` and `loadgen`
are not reachable from the controller, and `collect` of those needs Linux.
Probe them from inside the VM (`docker run --rm --network host busybox wget -qO- <url>`).
