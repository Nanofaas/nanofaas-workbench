# loadgen (component `loadgen`)

k6 load generator, run as a **job** (container form only), image `grafana/k6` 2.3.0 pinned by digest.

| `config` key | Default | |
| --- | --- | --- |
| `script` | required | bundled script under `files/scripts/` (`one-shot.js`, moved verbatim from nanolab) |
| `env` | `{}` | passed to k6 (`ONE_SHOT_SCHEDULE`, `ONE_SHOT_VUS`, `ONE_SHOT_DURATION`) |
| `mounts` | `{}` | `{host_path: container_path}`, read-only |
| `output_dir` | required | host path mounted read-write at `/out` |
| `user` | invoking user's `uid:gid` | k6 runs as this user, so output files belong to the caller |
| `network` | `host` | host network so loopback URLs in schedules work |

Deploy runs `k6 run --quiet --log-format=json --log-output=file=/out/generator.jsonl /scripts/<script>`
detached (`restart_policy: no`), stderr to `/out/generator.stderr`. Deploy returns once the container
is running or has exited 0. Undeploy stops with a 10 s grace and removes it. `collect` fetches
`output_dir` as `loadgen-out.tar.gz` only when the host is not the controller.

Exit status: `docker inspect wb-<name> --format '{{.State.Status}} {{.State.ExitCode}}'`.

## generator.jsonl

One k6 JSON log object per line; the script's `console.log(JSON.stringify(row))` arrives as a
string in `msg`. A reader does `row = json.loads(json.loads(line)["msg"])` and keeps rows whose
`event` is `emitted` or `result` (what nanolab's `generator_rows` does). Other lines (k6 errors,
no `event`) are skipped.
