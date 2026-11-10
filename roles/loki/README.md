# loki (component `loki`)

Log store. Container form: default bridge network, port published as `<bind>:<port>:3100`,
`data_dir` bind-mounted at `/loki`, config file mounted at `/etc/loki/loki.yaml`.

| `config` key | Default | |
| --- | --- | --- |
| `port` | required | published host port; readiness is GET `/ready` |
| `bind` | `127.0.0.1` | |
| `data_dir` | required | host path mounted at `/loki`; the caller owns the raw archive. Created with mode 0777 when missing (Loki runs as uid 10001); an existing dir keeps its mode, so the caller makes it writable by uid 10001 |
| `config_file` | bundled `files/loki.yaml` | controller path to a Loki config in the container layout |

The bundled file is a verbatim copy of nanoFaaS `deploy/observability/loki.yaml` at `401391a0`.
Retention and limits live in that file, not in the role config (the file owns them).

`collect`: with `collect_dir` set on a non-local host, the data dir is fetched as a tarball into
`<collect_dir>/<inventory_hostname>/<instance>/`; on the controller it is a no-op.
Image pinned by digest (`loki_image`, 3.7.8). Pod form (`collect` is not implemented and fails clearly): a Deployment with a Service on `config.port`; the data dir is an `emptyDir`.
