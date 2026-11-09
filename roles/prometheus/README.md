# prometheus (component `prometheus`)

Resource metrics store. Container form: **host network** (targets include the caller's loopback
tunnels), listening on `<bind>:<port>` via `--web.listen-address`; admin API enabled.

| `config` key | Default | |
| --- | --- | --- |
| `port` | required | readiness and API port |
| `bind` | `127.0.0.1` | |
| `data_dir` | required | host path mounted at `/prometheus` (created 0777: Prometheus runs as nobody) |
| `scrape_interval` | `5s` | |
| `retention` | `7d` | |
| `jobs` | `{}` | `{<job>: [{target: "host:port", labels: {…}}]}`; every job has `honor_timestamps: false`; an empty list is valid |

The rendered config is `/tmp/wb-<instance>/prometheus.yml`; a changed file restarts the container.

`collect`: POST `/api/v1/admin/tsdb/snapshot`, archive the snapshot (under `data_dir/snapshots`) to
`<collect_dir>/<instance>/prometheus-snapshot.tar.gz`. Image pinned by digest (`prometheus_image`,
3.16.0). Snapshots accumulate under `data_dir/snapshots` (nothing prunes them). Pod form: a Deployment on the host network (as the container form), the data dir is an `emptyDir`.
