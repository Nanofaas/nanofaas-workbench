# log-collector (component `log-collector`)

fluent-bit shipping container logs to Loki. Container form: **host network**; read-only root fs,
`cap_drop: ALL`, `no-new-privileges`, log driver `local` (10m x 2).

| `config` key | Default | |
| --- | --- | --- |
| `port` | required | fluent-bit HTTP port (the config files set it); readiness and `collect` |
| `config_files` | required | `{fluent-bit.conf: <path>, parsers.conf: <path>}` on the controller; the role ships none (use nanoFaaS' `deploy/observability`) |
| `loki` | required | `{host, port, uri, tls}` -> `LOKI_HOST`, `LOKI_PORT`, `LOKI_URI` (default `/loki/api/v1/push`), `LOKI_TLS` (`On`/`Off`, default `Off`) |
| `storage_dir` | required | host path mounted at `/var/lib/fluent-bit` (created 0777) |
| `docker_root` | `/var/lib/docker` | its `containers` dir is mounted ro at `/var/log/containers` |
| `cpus`, `memory_mib` | unset | container limits |
| `env` | `{}` | extra environment (e.g. the `NANOFAAS_*` values the nanoFaaS config reads) |

A changed config file restarts the container.

`collect`: GET `/api/v2/metrics/prometheus` to `<collect_dir>/<instance>/metrics.txt`; on a
non-local host also the storage dir as `storage.tar.gz` (locally it is the caller's already).
Image pinned by digest (`log_collector_image`, 5.1.3). Pod form: a Deployment on the host network; `storage_dir` is a `hostPath` and `docker_root/containers` is mounted read-only at `/var/log/containers`, as in the container form (on containerd nodes those are symlinks into `/var/log/pods`, which is not mounted).
