# Host vars format

A JSON file, passed as `-e workbench_vars=<path>`. Every playbook loads it and
validates it first.

```json
{"instances": [{"name": "loki", "component": "loki", "form": "container",
                "cpuset": "2-3", "config": {"port": 3100}}],
 "collect_dir": "/abs/controller/path"}
```

| Field | Rule |
| --- | --- |
| `name` | `^[a-z0-9-]+$`, unique in the file |
| `component` | `prometheus`, `loki`, `log-collector`, `loadgen`, `node-exporter`, `cadvisor`, `supervisor` |
| `form` | `container` (default) or `pod` |
| `cpuset` | kernel CPU list (`2-3`, `0,4-5`) or absent |
| `config` | component-specific, see below |
| `collect_dir` | optional; an absolute path on the controller (a relative one is rejected) |

`config` keys per component: [prometheus](../roles/prometheus/README.md),
[loki](../roles/loki/README.md), [log-collector](../roles/log_collector/README.md),
[loadgen](../roles/loadgen/README.md), [node-exporter](../roles/node_exporter/README.md),
[cadvisor](../roles/cadvisor/README.md), [supervisor](../roles/supervisor/README.md); the pod
form's extra keys (`kubeconfig`, `namespace`) in [common](../roles/common/README.md).

Directories the vars name (`data_dir`, `storage_dir`, `output_dir`) are created when missing; one
that already exists keeps its owner and mode, and the caller makes it writable by the component
(see each role's README).

## Target prerequisites

- **Container form** (and `collect` of any form that has something to fetch): a Docker engine the
  connection user can reach, and on the target a Python with the `requests` and `docker` packages,
  which `community.docker` needs. `collect` archives inside a container, so `tar` is not needed.
- **Pod form:** `helm` 3 and `kubectl` on the target, and a kubeconfig there (`config.kubeconfig`,
  or the default one). The chart is copied to the target, helm runs there.
- `localhost` / `127.0.0.1` run with the controller's own Python (`ansible_playbook_python`).

Install: `ansible-galaxy collection install git+https://github.com/Nanofaas/nanofaas-workbench.git,v<version>`

Run: `ansible-playbook -i <inventory> -e workbench_vars=<file> nanofaas.workbench.deploy`
(also `.collect`, `.undeploy`).
