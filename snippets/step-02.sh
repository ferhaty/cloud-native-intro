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
