# Orders API: local cloud-native introduction

For the current interactive reader path, follow the [seven-step guide](STEP-BY-STEP.md) in one Bash terminal. Its [manual acceptance workflow](.github/workflows/steps-acceptance.yml) executes the exact blocks, with additional checks kept outside the guide. The automated script below remains available as a separate path.

Checked on 2 November 2026 on a standard GitHub-hosted Ubuntu 24.04.5 x86-64 runner: Docker client/server 28.0.4, kind v0.33.0, kubectl and Kubernetes v1.37.0, Python 3.13.18 in the application container. Install Docker, kind and kubectl before starting; allow about 15 minutes. No cloud account is needed.

Save the following block as `session.sh` in this directory, then run `bash session.sh`. Do not source it or paste it into an interactive shell: it relies on script exit for cleanup. Docker's daemon must already work. Cluster discovery must succeed; any existing kind cluster (including `intro`) is explicitly refused. Use this lab exclusively: do not create or replace `intro` concurrently. The session uses its own kubeconfig and arms cleanup only after successful creation.
```bash
set -euo pipefail
export KIND_EXPERIMENTAL_PROVIDER=docker
clusters=$(kind get clusters) || { printf '%s\n' 'Cannot discover kind clusters; stopping.' >&2; exit 1; }
if [[ -n "$clusters" ]]; then printf 'Refusing existing kind clusters: %s\n' "$clusters" >&2; exit 1; fi
test ! -e "$PWD/.intro-kubeconfig"
export KUBECONFIG="$PWD/.intro-kubeconfig"
cleanup() {
  rc=$?
  if (( rc != 0 )); then
    k --request-timeout=10s get pods,deployments -o wide || true
    k --request-timeout=10s get events --sort-by=.lastTimestamp || true
  fi
  if ! kind delete cluster --name intro; then printf '%s\n' 'Cleanup failed; inspect intro and retry deletion.' >&2; exit 1; fi
  rm -f "$KUBECONFIG"
  exit "$rc"
}
k() { kubectl --context kind-intro "$@"; }
docker build -t orders-api:1.0.0 .
kind create cluster --name intro --wait 120s \
  --image kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
trap cleanup EXIT # Only a successful creation gives this session ownership.
kind load docker-image orders-api:1.0.0 --name intro
k apply -f orders.yaml
k rollout status deployment/orders --timeout=120s
k scale deployment orders --replicas=3
k rollout status deployment/orders --timeout=120s
k get pods -l app=orders
k run client --restart=Never \
  --image=curlimages/curl:8.16.0@sha256:463eaf6072688fe96ac64fa623fe73e1dbe25d8ad6c34404a669ad3ce1f104b6 --command -- sleep 3600
k wait --for=condition=Ready pod/client --timeout=120s
k exec client -- sh -ec 'for i in $(seq 10); do curl -fsS --max-time 5 http://orders/; echo; done'
old=$(k get pods -l app=orders -o jsonpath='{.items[0].metadata.name}')
k delete pod "$old" --wait=true --timeout=120s
k wait --for=condition=Ready pod -l app=orders --timeout=120s
k rollout status deployment/orders --timeout=120s
k get pods -l app=orders
k exec client -- curl -fsS --max-time 5 http://orders/
```

After a workload error or timeout, the exit trap prints pod/Deployment status and events before deletion; each diagnostic API request has a 10-second timeout and diagnostic failure does not skip cleanup. Capture output with `bash session.sh >session.log 2>&1`, inspect `session.log`, correct the cause, then rerun. A failed creation never arms the deletion trap: inspect `kind get clusters` and `docker ps -a` before any manual action. If creation left a partial lab, confirm it is yours before running `kind delete cluster --name intro` and removing `.intro-kubeconfig`. If deletion fails, the script reports failure and keeps that kubeconfig for inspection/retry. Hard process termination cannot guarantee cleanup. CI uses a disposable VM; the final workflow step verifies cleanup rather than blindly deleting a cluster.

The manifest starts at one replica; scaling makes three. Reapplying it later resets the declared count to one. `imagePullPolicy` is intentionally unset: a non-`latest` tag defaults to `IfNotPresent`, allowing kind's loaded image. `/healthz` returns plain text; `/` returns JSON. This is a teaching HTTP server, not a production API.

Each in-cluster curl opens a new connection through Service DNS; `served_by` may vary, but ten requests do not guarantee seeing every replica. Port-forwarding would pin a pod instead. Compare pod names before and after deletion: the replacement has a new name. Readiness and replacement are asynchronous; the waits are deliberate. The base, client and kind node images are digest-pinned.


## Observed result

Trimmed output from the [successful hosted run](https://github.com/ferhaty/cloud-native-intro/actions/runs/41444261743), not a prediction of your pod names or timings:

```text
deployment.apps/orders scaled
NAME                      READY   STATUS    RESTARTS   AGE
orders-7fcd4fc5c8-8k26t   1/1     Running   0          3s
orders-7fcd4fc5c8-khrrv   1/1     Running   0          1s
orders-7fcd4fc5c8-lpx9x   1/1     Running   0          1s
{"orders": [], "served_by": "orders-7fcd4fc5c8-khrrv", "version": "1.0.0"}
{"orders": [], "served_by": "orders-7fcd4fc5c8-8k26t", "version": "1.0.0"}
{"orders": [], "served_by": "orders-7fcd4fc5c8-lpx9x", "version": "1.0.0"}
pod "orders-7fcd4fc5c8-8k26t" deleted from default namespace
NAME                      READY   STATUS    RESTARTS   AGE
orders-7fcd4fc5c8-kcwrq   1/1     Running   0          32s
orders-7fcd4fc5c8-khrrv   1/1     Running   0          36s
orders-7fcd4fc5c8-lpx9x   1/1     Running   0          36s
Deleted nodes: ["intro-control-plane"]
```

The checks confirmed one Ready replica became three, requests through Service DNS reached multiple replicas, and deleting `orders-7fcd4fc5c8-8k26t` produced `orders-7fcd4fc5c8-kcwrq` with a new UID. All three replicas were Ready afterwards; another 40 requests and the fully qualified Service health URL succeeded. The cluster, node container and dedicated kubeconfig were removed.

The manual [acceptance workflow](.github/workflows/acceptance.yml) extracts the Bash block above and inserts additional assertions; it is not required to follow the exercise. It uses a standard hosted runner, read-only repository permissions and no repository secrets or cloud credentials. This single-node Linux test does not establish multi-node availability, zero-downtime deletion, production readiness, load capacity, or compatibility with macOS, Windows, ARM or rootless runtimes. Requests are checked before and after replacement, not continuously during it.
