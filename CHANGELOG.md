# Changelog

## 0.2.0 — release candidate, not published

- Collect artifacts now use `<collect_dir>/<inventory_hostname>/<instance>/...`.
  Update readers together with the collection; historical archives stay in place.
- Prometheus and supervisor pods use pod networking and reachable ClusterIP
  Services. Their default bind is `0.0.0.0`; explicit loopback binds are refused.
  Prometheus pod admin API stays disabled; container snapshots remain supported.
- Loadgen pods require `config.node_name` and pre-existing input/output directories
  on that node. Deploy waits for Running or successful completion, and rejects
  Failed or Pending timeout; an active Job counter alone no longer passes.
- Malformed non-string supervisor target kinds return HTTP 400 without changing
  targets or breaking the status endpoint.

## 0.1.1

- cAdvisor runs with `--allow_dynamic_housekeeping=false`, so `housekeeping_interval` holds for idle containers too.
- Docs: `community.docker` needs `requests` on the target, not the Docker SDK.

## 0.1.0

- Collection skeleton and the host vars format.
- Pod form: the Helm chart in `chart/` and the pod branch of every role.
- Components as roles in container form: node-exporter, cadvisor, loki, log-collector, prometheus, loadgen, supervisor.
- Supervisor service and image (`ghcr.io/nanofaas/workbench-supervisor`).
- Playbooks `deploy`, `collect`, `undeploy`.
- Release workflow: tag `v*` pushes the supervisor image and a GitHub Release with the collection tarball.
