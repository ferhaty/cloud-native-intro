kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro apply -f orders.yaml &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro rollout status deployment/orders --timeout=120s &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro get pods -l app=orders
