# cadvisor (component `cadvisor`)

Container metrics. Container form: default bridge network with the port published, no `pid: host`;
read-only `/sys`, `/sys/fs/cgroup`, `/var/lib/docker`, the Docker socket and `/run/containerd`
(Docker's containerd image store needs it for the docker factory).
Runs with `--docker_only=true --store_container_labels=true`, so Docker labels appear as
`container_label_*` series labels.

| `config` key | Default | |
| --- | --- | --- |
| `port` | `8080` | read back at `http://<host>:<port>/metrics` |
| `bind` | `127.0.0.1` | address the published port binds to |
| `housekeeping_interval` | `5s` | |

The image is pinned by digest in `defaults/main.yml` (`cadvisor_image`). Pod form: not implemented yet.

Mounts, all read-only, and why: `/` at `/rootfs` (filesystem and disk stats), `/sys` and `/sys/fs/cgroup`
(cgroup counters), `/var/lib/docker` (container layer sizes), the single file `/var/run/docker.sock`
(container names and labels; the whole `/var/run` is not needed), and `/run/containerd` (Docker's
containerd image store; without it the docker factory is not registered). `/proc` is not needed.

Pod form: one Pod pinned with `nodeName` from required `config.node_name`, `hostPID: true`, the same read-only host mounts as `hostPath`, and a Service on `config.port`.
