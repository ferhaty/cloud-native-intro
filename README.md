# Orders API: local cloud-native introduction
Checked on 2 November 2026 on a standard GitHub-hosted Ubuntu 24.04.5 x86-64 runner: Docker client/server 28.0.4, kind v0.33.0, kubectl and Kubernetes v1.37.0, Python 3.13.18 in the application container. Install Docker, kind and kubectl before starting; allow about 15 minutes. No cloud account is needed.

Run this session in a fresh Bash shell from this directory. It refuses existing kind clusters and uses its own kubeconfig. Cleanup runs on exit, including failure. Docker's daemon must already work; no cloud account is needed.
```bash
set -euo pipefail
export KIND_EXPERIMENTAL_PROVIDER=docker
test -z "$(kind get clusters)" # Stop rather than touch existing labs.
test ! -e "$PWD/.intro-kubeconfig"
export KUBECONFIG="$PWD/.intro-kubeconfig"
cleanup() { kind delete cluster --name intro && rm -f "$KUBECONFIG"; }
trap cleanup EXIT
k() { kubectl --context kind-intro "$@"; }
docker build -t orders-api:1.0.0 .
kind create cluster --name intro --wait 120s \
  --image kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
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
cleanup; trap - EXIT
```

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
