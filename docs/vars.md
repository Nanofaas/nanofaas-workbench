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
| `config` | component-specific |
| `collect_dir` | optional, absolute controller path |

Install: `ansible-galaxy collection install git+https://github.com/Nanofaas/nanofaas-workbench.git,v<version>`

Run: `ansible-playbook -i <inventory> -e workbench_vars=<file> nanofaas.workbench.deploy`
(also `.collect`, `.undeploy`).
