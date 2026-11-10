# supervisor (component `supervisor`)

Watches targets through the workbench Prometheus and HTTP probes and reports
`healthy` / `degraded` / `fault`. It only signals: it never stops, kills or
restarts anything. Container form: **host network** (Prometheus and HTTP targets
are on the caller's loopback), read-only root, all capabilities dropped, runs as
`nobody`. Source: `supervisor/src/workbench_supervisor`, image
`images/supervisor/Dockerfile`.

| `config` key | Default | |
| --- | --- | --- |
| `port` | required | API port, waited on |
| `bind` | `127.0.0.1` | |
| `prometheus_url` | required | e.g. `http://127.0.0.1:9090` |
| `interval` | `5` | seconds between check rounds |
| `targets` | `{}` | initial targets, `{<name>: <target>}` |
| `image` | `supervisor_image` | e.g. a locally built `:test` tag |

A target is `{"kind": …, "params": {…}, "toleratedSeconds": 0, "graceSeconds": 30}` (both finite,
>= 0; measured on a monotonic clock, so wall-clock steps do not shift them). Names, also those in
`targets`, match `[A-Za-z0-9_.-]{1,128}`.

Start-up grace: for `graceSeconds` after a target is created (its `PUT`, or the supervisor's
start for `--targets`) a failing check only makes it `degraded`, never `fault`, so targets
checked before Prometheus has scraped anything do not fault. After the grace the tolerance
applies, counted from the later of the failure's start and the end of the grace: a failure
that began inside the grace and is still going faults `toleratedSeconds` after the grace ends.

**`swap_quiet` callers: set `minAvailableBytes`.** Its 8 GiB default fits a large host only; on a
smaller one the target fails at once.

| `kind` | `params` | fails when |
| --- | --- | --- |
| `scrape_up` | `job`, `labels` (`{}`, no `job` key) | any `up{job=…, <labels>}` is not 1, or none exists |
| `container_running` | `name`, `node`, `staleSeconds` (3 × `interval`) | `time() - container_last_seen{name=…, node=…} > staleSeconds`, or none exists; set `staleSeconds` above the cAdvisor scrape interval plus its housekeeping interval when those are longer |
| `swap_quiet` | `node`, `maxSwapPages` (`256`), `minAvailableBytes` (8 GiB), `window` (`30s`) | `increase(node_vmstat_pswpin[W]) + increase(node_vmstat_pswpout[W]) > maxSwapPages` or `node_memory_MemAvailable_bytes < minAvailableBytes` |
| `http_ok` | `url`, `timeoutSeconds` (`5`) | the GET is not 2xx |

An error running a check (Prometheus unreachable, connection refused) is a
failing target, with the error as `detail`.

API:

- `PUT /targets/<name>` (name `[A-Za-z0-9_.-]{1,128}`): add or replace → 204; an invalid
  target → 400. Putting the identical target again keeps its state; putting a changed
  target starts it over, which also clears a sticky fault.
- `DELETE /targets/<name>` → 204, also when absent. A removed target is never reported again.
- `GET /status` → `{"state", "targets": {name: {"kind", "failing", "since", "detail"}},
  "anomalies": [{"target", "kind", "detail", "since"}], "checkedAt"}` (`checkedAt` is the end
  of the last check round, `null` before the first). A target failing for less than
  `toleratedSeconds` makes the state `degraded`; for longer, `fault`. `fault` is sticky
  until the target is removed; the anomaly then keeps the detail that caused it.
- A query string is ignored on every path.
- `GET /metrics` → `workbench_supervisor_state{state="healthy|degraded|fault"} 0|1`,
  `workbench_supervisor_target_failing{target=…,kind=…} 0|1`.

`collect`: nothing. Pod form: a Deployment on the host network with a Service on `config.port`.

The pod form uses pod networking and a ClusterIP Service, listening on `0.0.0.0`
by default. Explicit loopback listeners are rejected. Targets on the node must
use an explicit address or Service DNS; pod loopback refers to the pod itself.
