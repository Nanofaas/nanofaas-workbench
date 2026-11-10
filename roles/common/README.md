# common

Not a component: shared task files the component roles include.

- `container_deploy.yml` runs one instance with `community.docker.docker_container`
  as `wb-<instance name>` with the two `nanofaas.workbench/*` labels and
  `cpuset_cpus` from `instance.cpuset`, then waits for `wb_port` when it is set (omit it for a job).
  Inputs: `instance`, `wb_image`, optional `wb_port`, `wb_command`,
  `wb_entrypoint`, `wb_user` (`uid:gid`), `wb_restart_policy` (default `unless-stopped`; `"no"` for a job),
  `wb_volumes`, `wb_ports`, `wb_network_mode` (default bridge), `wb_pid_mode`.
- `container_undeploy.yml` removes `wb-<instance name>` if it carries the
  instance label; a missing instance is success. Stops with SIGTERM and a 10 s grace
  when `wb_graceful` is true, otherwise kills immediately.
- `ensure_dir.yml` creates `wb_dir` with `wb_mode` only when it is missing; an existing directory
  keeps its owner and mode.
- `caller_ids.yml` sets `common_caller_ids` to the connection user's `uid:gid` on the target.
- `fetch_dir_tarball.yml` archives `wb_src_dir` on the target in a throwaway container
  (`common_probe_image`, root inside, no network), so files a component wrote as another uid or
  with mode 0600 are read without `become`; the tarball is chowned to the connection user, fetched
  to `<collect_dir>/<inventory_hostname>/<instance>/<wb_archive>` and the scratch dir removed.
- `pod_deploy.yml` installs the chart for one instance (inputs `wb_key`, `wb_values`, optional `wb_files`,
  `wb_files_dir`, `wb_cpu`, `wb_memory`, `wb_wait`); `pod_undeploy.yml` runs `helm uninstall`
  (a missing release is success). The chart is copied to `/tmp/wb-<instance>/chart` on the target first (helm runs there); undeploy removes `/tmp/wb-<instance>`. `pod_collect_unsupported.yml` fails `collect` for pod-form instances of components that collect something.

## Pod form

`form: pod` installs the collection's chart (`chart/`) as the Helm release `wb-<instance>` with
`kubernetes.core.helm`, from the target host (it needs `helm` 3, a kubeconfig, and for the loadgen
`kubectl`). Optional `config.kubeconfig` and `config.namespace` (default `default`). Objects are named
`wb-<instance>` and carry `nanofaas.workbench/instance` and `nanofaas.workbench/component`; a
`cpuset` becomes `resources.requests/limits.cpu` equal to its CPU count. Config files are rendered
as in the container form and passed to the chart, whose ConfigMap carries them byte for byte.
Pod form differences: the data/storage dirs below are an `emptyDir` unless stated; `bind` only
matters for components on the host network.
