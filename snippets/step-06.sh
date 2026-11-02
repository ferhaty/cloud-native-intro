pod=$(kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro get pods -l app=orders -o jsonpath='{.items[0].metadata.name}') &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro delete pod "$pod" --wait=true --timeout=120s &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro wait --for=condition=Ready pod -l app=orders --timeout=120s &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro rollout status deployment/orders --timeout=120s &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro get pods -l app=orders &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro exec client -- curl -fsS --max-time 5 http://orders/
