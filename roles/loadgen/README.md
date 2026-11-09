# loadgen (component `loadgen`)

k6 load generator, run as a **job** (container or pod form), image `grafana/k6` 2.3.0 pinned by digest.

| `config` key | Default | |
| --- | --- | --- |
| `script` | required | bundled script under `files/scripts/` (`one-shot.js`, moved verbatim from nanolab) |
| `env` | `{}` | passed to k6 (`ONE_SHOT_SCHEDULE`, `ONE_SHOT_VUS`, `ONE_SHOT_DURATION`) |
| `mounts` | `{}` | `{host_path: container_path}`, read-only |
| `output_dir` | required | host path mounted read-write at `/out`; created 0755 when missing, an existing dir keeps its mode (it must be writable by `user`) |
| `user` | invoking user's `uid:gid` | k6 runs as this user, so output files belong to the caller |
| `network` | `host` | host network so loopback URLs in schedules work |

Deploy runs `k6 run --quiet --log-format=json --log-output=file=/out/generator.jsonl /scripts/<script>`
detached (`restart_policy: no`), stderr to `/out/generator.stderr`. Deploy returns once the container
is running or has exited 0.

A loadgen instance runs once, in both forms: deploying one whose job is still running is a no-op;
deploying one whose job has already finished (container exited, Job succeeded or failed) fails with
`loadgen <name> already ran; undeploy it first`, so a retried deploy never duplicates load or
evidence; only a missing instance starts a new run. Undeploy stops with a 10 s grace and removes it. `collect` fetches
`output_dir` as `loadgen-out.tar.gz` only when the host is not the controller.

Pod form (`collect` is not implemented and fails clearly): a Kubernetes Job (`backoffLimit: 0`, `restartPolicy: Never`, host network), the script in the
ConfigMap, `output_dir` a `hostPath` on the node, `mounts` read-only `hostPath`s. Deploy returns once the Job is active or finished and fails when
it has failed. Exit status:
`kubectl get job wb-<name> -o jsonpath='{.status.succeeded}/{.status.failed}'` (`1/` succeeded, `/1` failed);
the k6 exit code is in `kubectl get pod -l nanofaas.workbench/instance=<name> -o jsonpath='{.items[0].status.containerStatuses[0].state.terminated.exitCode}'`.

Container form exit status: `docker inspect wb-<name> --format '{{.State.Status}} {{.State.ExitCode}}'`.

## generator.jsonl

One k6 JSON log object per line; the script's `console.log(JSON.stringify(row))` arrives as a
string in `msg`. A reader does `row = json.loads(json.loads(line)["msg"])` and keeps rows whose
`event` is `emitted` or `result` (what nanolab's `generator_rows` does). Other lines (k6 errors,
no `event`) are skipped.
