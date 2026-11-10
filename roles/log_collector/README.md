# log-collector (component `log-collector`)

fluent-bit shipping container logs to Loki. Container form: **host network**; read-only root fs,
`cap_drop: ALL`, `no-new-privileges`, log driver `local` (10m x 2).

| `config` key | Default | |
| --- | --- | --- |
| `port` | required | fluent-bit HTTP port (the config files set it); readiness and `collect` |
| `config_files` | required | `{fluent-bit.conf: <path>, parsers.conf: <path>}` on the controller; the role ships none (use nanoFaaS' `deploy/observability`) |
| `loki` | required | `{host, port, uri, tls}` -> `LOKI_HOST`, `LOKI_PORT`, `LOKI_URI` (default `/loki/api/v1/push`), `LOKI_TLS` (`On`/`Off`, default `Off`) |
| `storage_dir` | required | host path mounted at `/var/lib/fluent-bit` (created 0777 when missing; an existing dir keeps its mode, so the caller makes it writable by the container's root) |
| `docker_root` | `/var/lib/docker` | its `containers` dir is mounted ro at `/var/log/containers` |
| `cpus`, `memory_mib` | unset | container limits |
| `collect_mode` | `snapshot` | `metrics` reads only counters; `snapshot` also archives remote storage; `final` stops the owned collector and archives storage on every host, including localhost |
| `stop_timeout` | `15` | seconds allowed for graceful shutdown during final collection |
| `env` | `{}` | extra environment (e.g. the `NANOFAAS_*` values the nanoFaaS config reads) |

A changed config file restarts the container.

`collect` reads `/api/v2/metrics/prometheus` into
`<collect_dir>/<inventory_hostname>/<instance>/metrics.txt`. A metrics failure
still fails the action, but collection attempts independent raw recovery first.

For `collect_mode: final`, stop the producers and drain according to the caller's
policy before collecting. The role verifies container ownership, stops it,
collects its final logs/identity/stats, and saves `storage.tar.gz` with a SHA-256
sidecar. It keeps the source directory and records `collection.json` even when
collection fails: `mode`, `metricsAvailable`, `quiesced`, `archiveSha256`,
`sourcePreserved`, and `containerEvidenceError`. An absent container is already
quiesced; an unrelated container is never stopped. Container diagnostics failures
do not prevent attempting the buffer archive.

A caller can accept a partial collection's raw archive only after verifying a
**fresh** final receipt, `quiesced: true`, and the actual archive checksum. A stale
receipt from a previous invocation is not proof of recovery. Whether missing
metrics invalidate an experiment or require retaining its VM is the caller's
policy; this collection never deletes VMs or source buffers.

Image pinned by digest (`log_collector_image`, 5.1.3). Pod form: a Deployment on the host network; `storage_dir` is a `hostPath` and `docker_root/containers` is mounted read-only at `/var/log/containers`, as in the container form, plus `/var/log/pods` read-only so containerd's symlinks in `/var/log/containers` resolve. `collect` is not implemented for the pod form and fails clearly.
