if [[ "${intro_created:-false}" == true ]]; then
  kind delete cluster --name intro --kubeconfig "$PWD/.intro-kubeconfig" &&
  rm -f "$PWD/.intro-kubeconfig" &&
  intro_created=false
else
  printf '%s\n' 'No successfully created cluster recorded in this session; nothing deleted.'
fi
