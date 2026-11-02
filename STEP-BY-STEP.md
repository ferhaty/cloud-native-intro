## How do you run your first workload?

Build an application image, run it in a local Kubernetes cluster, then scale it and observe how Kubernetes replaces a deleted Pod. You will use Docker, kind and kubectl on a disposable workstation or VM; no cloud account is needed. kind runs Kubernetes nodes in containers.[\[51\]](https://kind.sigs.k8s.io/docs/user/quick-start/)

Use Bash with Docker's daemon running and kind and kubectl installed. Work in a new directory and keep the same terminal and directory throughout. Run the blocks in order, stopping if any command fails. The lab uses a dedicated `.intro-kubeconfig` file and the explicit `kind-intro` context, rather than your usual cluster configuration. Reserve the kind name `intro` for this session: it must not already exist or be created by another session while you work.

The [example repository](https://github.com/ferhaty/cloud-native-intro) also contains the full automated script. Here, you will run the exercise in seven steps.

### 1. Build the application image

Create `app.py` and `Dockerfile` in your working directory. The application returns an empty orders list, its hostname in `served_by` and a version; `/healthz` returns `ok`. It accepts no order submissions and connects to no database. Python's `http.server` is not intended as a production server.[\[52\]](https://docs.python.org/3/library/http.server.html)

**`app.py`**

```python
from http.server import BaseHTTPRequestHandler, HTTPServer
import json, os, socket

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            body, content_type = b"ok", "text/plain; charset=utf-8"
        else:
            body = json.dumps({
                "orders": [],
                "served_by": socket.gethostname(),
                "version": os.getenv("APP_VERSION", "dev"),
            }).encode()
            content_type = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    HTTPServer(("", 8080), Handler).serve_forever()
```

**`Dockerfile`**

```dockerfile
FROM python:3.13-slim@sha256:ae14d4ce8771606477a81446e7ef429edd6762305fc50c84507c1041fa8285d1
WORKDIR /app
COPY app.py .
ENV APP_VERSION=1.0.0
EXPOSE 8080
USER 1000
CMD ["python", "app.py"]
```

The Dockerfile packages Python and the application, sets its version and defines the startup command. Build that image with:

```shell
docker build -t orders-api:1.0.0 .
```

This creates the local image `orders-api:1.0.0`; you do not need Python installed on the host.

### 2. Create the local cluster and load the image

This check refuses an existing `intro` cluster or kubeconfig file and does not create anything if cluster discovery fails. Only successful creation marks the cluster as belonging to this session.

```shell
export KIND_EXPERIMENTAL_PROVIDER=docker
intro_created=false
if ! clusters=$(kind get clusters); then
  printf '%s\n' 'Cannot discover kind clusters; stop here.' >&2
  false
elif printf '%s\n' "$clusters" | grep -Fxq intro; then
  printf '%s\n' 'The intro cluster already exists; stop here.' >&2
  false
elif [[ -e "$PWD/.intro-kubeconfig" || -L "$PWD/.intro-kubeconfig" ]]; then
  printf '%s\n' '.intro-kubeconfig already exists; stop here.' >&2
  false
else
  kind create cluster --name intro --wait 120s \
    --kubeconfig "$PWD/.intro-kubeconfig" \
    --image kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5 &&
  intro_created=true &&
  kind load docker-image orders-api:1.0.0 --name intro
fi
```

After success, Kubernetes is running locally and its node has your application image. If creation fails, stop and inspect what remains; do not delete a cluster whose ownership you have not established.

### 3. Deploy the workload

Save `orders.yaml` beside the application files. The Deployment requests one replica. The Service selects Pods labelled `app: orders` and routes port 80 to the application's port 8080. The readiness probe checks `/healthz` before a Pod receives Service traffic.[\[35\]](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)[\[39\]](https://kubernetes.io/docs/concepts/services-networking/service/)

**`orders.yaml`**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders
spec:
  replicas: 1
  selector:
    matchLabels: { app: orders }
  template:
    metadata:
      labels: { app: orders }
    spec:
      containers:
        - name: orders
          image: orders-api:1.0.0
          ports: [{ containerPort: 8080 }]
          readinessProbe:
            httpGet: { path: /healthz, port: 8080 }
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits: { memory: 128Mi }
---
apiVersion: v1
kind: Service
metadata:
  name: orders
spec:
  selector: { app: orders }
  ports: [{ port: 80, targetPort: 8080 }]
```

The non-`latest` image tag defaults to `IfNotPresent`, so Kubernetes can use the image loaded into kind.[\[33\]](https://kubernetes.io/docs/concepts/containers/images/)

```shell
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro apply -f orders.yaml &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro rollout status deployment/orders --timeout=120s &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro get pods -l app=orders
```

The rollout wait allows time for the application to start. After it succeeds, the listing should show one ready orders Pod.

### 4. Send a request

Start a small client Pod, wait for it to become ready, then use it to call the Service from inside the cluster.

```shell
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro run client --restart=Never \
  --image=curlimages/curl:8.16.0@sha256:463eaf6072688fe96ac64fa623fe73e1dbe25d8ad6c34404a669ad3ce1f104b6 --command -- sleep 3600 &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro wait --for=condition=Ready pod/client --timeout=120s &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro exec client -- curl -fsS --max-time 5 http://orders/
```

The JSON response should contain `orders: []`, version `1.0.0` and the serving Pod's hostname. Using the in-cluster Service name exercises Service routing rather than forwarding directly to one Pod.

### 5. Scale to three replicas

Change the desired replica count, wait for the rollout and send several separate requests through the same Service.

```shell
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro scale deployment orders --replicas=3 &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro rollout status deployment/orders --timeout=120s &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro get pods -l app=orders &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro exec client -- sh -ec 'for i in $(seq 10); do curl -fsS --max-time 5 http://orders/; echo; done'
```

You should now see three ready orders Pods. Compare their names with the responses' `served_by` values: requests may reach different replicas, but a short sample need not visit every Pod or alternate between them.[\[39\]](https://kubernetes.io/docs/concepts/services-networking/service/)

### 6. Delete one Pod and observe its replacement

Capture one orders Pod's name and delete only that Pod. Then wait for the Deployment to recover and list its Pods again.

```shell
pod=$(kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro get pods -l app=orders -o jsonpath='{.items[0].metadata.name}') &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro delete pod "$pod" --wait=true --timeout=120s &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro wait --for=condition=Ready pod -l app=orders --timeout=120s &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro rollout status deployment/orders --timeout=120s &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro get pods -l app=orders &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro exec client -- curl -fsS --max-time 5 http://orders/
```

Compare the names with step 5: the deleted Pod should be gone and a new one should bring the count back to three. The ReplicaSet creates the replacement because the desired count has not changed. Replacement takes time; a successful request afterwards does not prove uninterrupted availability. Reapplying `orders.yaml` would restore its declared count of one.[\[36\]](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/)

This demonstrates reconciliation, not recovery from a failed host: all three replicas share one local node. A healthy endpoint also says nothing about correct business rules or recovery of persistent data.

### 7. Clean up explicitly

When finished, remove only the cluster successfully created in step 2. Run this in the same terminal and directory; the session flag prevents deletion when creation was refused or failed. Nothing is removed automatically when you close the terminal.

```shell
if [[ "${intro_created:-false}" == true ]]; then
  kind delete cluster --name intro &&
  rm -f "$PWD/.intro-kubeconfig" &&
  intro_created=false
else
  printf '%s\n' 'No successfully created cluster recorded in this session; nothing deleted.'
fi
```

This removes the local cluster, including its workload and client Pod, then removes the dedicated kubeconfig. Your source files and locally built image remain. If deletion fails, the kubeconfig and session flag remain available for a retry; inspect any remaining resources before proceeding.

