# Orders API: local cloud-native introduction
Not yet cluster-tested: this validation host lacks the cgroup v2 required by rootless kind. Local Python HTTP tests pass; they are not container tests. Use a disposable Docker-enabled machine, kind v0.33.0 and kubectl v1.37.0; allow about 15 minutes. These are proposed pins, not a tested-tool claim.

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

Each in-cluster curl opens a new connection through Service DNS; `served_by` may vary, but ten requests do not guarantee seeing every replica. Port-forwarding would pin a pod instead. Compare pod names before and after deletion: the replacement has a new name. Readiness and replacement are asynchronous; the waits are deliberate. No Kubernetes output is included because no cluster run has occurred. The Python and curl image digests were verified at Docker Hub; the node digest comes from kind's official release.
