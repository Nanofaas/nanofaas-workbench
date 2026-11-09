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
