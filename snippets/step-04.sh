kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro run client --restart=Never \
  --image=curlimages/curl:8.16.0@sha256:463eaf6072688fe96ac64fa623fe73e1dbe25d8ad6c34404a669ad3ce1f104b6 --command -- sleep 3600 &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro wait --for=condition=Ready pod/client --timeout=120s &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro exec client -- curl -fsS --max-time 5 http://orders/
