# common

Not a component: shared task files the component roles include.

- `container_deploy.yml` runs one instance with `community.docker.docker_container`
  as `wb-<instance name>` with the two `nanofaas.workbench/*` labels and
  `cpuset_cpus` from `instance.cpuset`, then waits for `wb_port`.
  Inputs: `instance`, `wb_image`, `wb_port`, optional `wb_command`,
  `wb_volumes`, `wb_ports`, `wb_network_mode` (default bridge), `wb_pid_mode`.
- `container_undeploy.yml` removes `wb-<instance name>` if it carries the
  instance label; a missing instance is success.
- `pod_unsupported.yml` fails clearly on `form: pod` until the pod form lands.
