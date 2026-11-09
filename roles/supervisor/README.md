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

A target is `{"kind": …, "params": {…}, "toleratedSeconds": 0}`:

| `kind` | `params` | fails when |
| --- | --- | --- |
| `scrape_up` | `job`, `labels` (`{}`) | any `up{job=…, <labels>}` is not 1, or none exists |
| `container_running` | `name`, `node` | `time() - container_last_seen{name=…, node=…} > 3 * interval`, or none exists |
| `swap_quiet` | `node`, `maxSwapPages` (`256`), `minAvailableBytes` (8 GiB), `window` (`30s`) | `increase(node_vmstat_pswpin[W]) + increase(node_vmstat_pswpout[W]) > maxSwapPages` or `node_memory_MemAvailable_bytes < minAvailableBytes` |
| `http_ok` | `url`, `timeoutSeconds` (`5`) | the GET is not 2xx |

An error running a check (Prometheus unreachable, connection refused) is a
failing target, with the error as `detail`.

API:

- `PUT /targets/<name>` (name `[A-Za-z0-9_.-]{1,128}`): add or replace → 204; an invalid
  target → 400. Putting the identical target again keeps its state.
- `DELETE /targets/<name>` → 204, also when absent. A removed target is never reported again.
- `GET /status` → `{"state", "targets": {name: {"kind", "failing", "since", "detail"}},
  "anomalies": [{"target", "kind", "detail", "since"}], "checkedAt"}` (`checkedAt` is the end
  of the last check round, `null` before the first). A target failing for less than
  `toleratedSeconds` makes the state `degraded`; for longer, `fault`. `fault` is sticky
  until the target is removed; the anomaly then keeps the detail that caused it.
- `GET /metrics` → `workbench_supervisor_state{state="healthy|degraded|fault"} 0|1`,
  `workbench_supervisor_target_failing{target=…,kind=…} 0|1`.

`collect`: nothing. Pod form: not implemented yet.
