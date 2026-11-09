# node_exporter (component `node-exporter`)

Host metrics. Container form: default bridge network with the port published; host `/proc` and `/sys` mounted
read-only at `/host/proc` and `/host/sys`.

| `config` key | Default | |
| --- | --- | --- |
| `port` | `9100` | read back at `http://<host>:<port>/metrics` |
| `bind` | `127.0.0.1` | address the published port binds to (`0.0.0.0` to expose it) |

The image is pinned by digest in `defaults/main.yml` (`node_exporter_image`).
The pod form is not implemented yet and fails clearly.
