# prometheus (component `prometheus`)

Resource metrics store. Container form: **host network** (targets include the caller's loopback
tunnels), listening on `<bind>:<port>` via `--web.listen-address`; admin API enabled (`--web.enable-admin-api`, always: `collect` needs its snapshot endpoint). **The admin API can delete series and wipe the TSDB with no authentication**; with `bind: 0.0.0.0` anyone who reaches the port can. Keep the default `127.0.0.1` unless the network is trusted.

| `config` key | Default | |
| --- | --- | --- |
| `port` | required | readiness and API port |
| `bind` | `127.0.0.1` | |
| `data_dir` | required | host path mounted at `/prometheus` (created 0777 when missing: Prometheus runs as nobody; an existing dir keeps its mode, so the caller makes it writable by uid 65534) |
| `scrape_interval` | `5s` | |
| `retention` | `7d` | |
| `jobs` | `{}` | `{<job>: [{target: "host:port", labels: {…}}]}`; every job has `honor_timestamps: false`; an empty list is valid |

The rendered config is `/tmp/wb-<instance>/prometheus.yml`; a changed file restarts the container.

`collect`: POST `/api/v1/admin/tsdb/snapshot`, archive the snapshot (under `data_dir/snapshots`) to
`<collect_dir>/<inventory_hostname>/<instance>/prometheus-snapshot.tar.gz`. Image pinned by digest (`prometheus_image`,
3.16.0). Snapshots accumulate under `data_dir/snapshots` (nothing prunes them). Pod form (`collect` is not implemented and fails clearly): a Deployment on pod networking, with an `emptyDir` data directory.

The pod form uses pod networking and a ClusterIP Service, listening on `0.0.0.0`
by default. Explicit loopback listeners are rejected. Targets on the node must
use an explicit address or Service DNS; pod loopback refers to the pod itself.
The admin API is disabled in pod form; snapshot collect is container-only.
