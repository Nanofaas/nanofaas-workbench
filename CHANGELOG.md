# Changelog

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
