kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro scale deployment orders --replicas=3 &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro rollout status deployment/orders --timeout=120s &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro get pods -l app=orders &&
kubectl --kubeconfig "$PWD/.intro-kubeconfig" --context kind-intro exec client -- sh -ec 'for i in $(seq 10); do curl -fsS --max-time 5 http://orders/; echo; done'
