#!/usr/bin/env bash
set -euo pipefail
fixture="$(mktemp -d)"
runtime_roots=()
network_roots=()
trap 'rm -rf -- "$fixture" "${runtime_roots[@]}" "${network_roots[@]}"' EXIT
mkdir -p "$fixture/bin"
cat >"$fixture/bin/podman" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == --cgroup-manager=cgroupfs && "$2" == --root ]]
[[ "$3" == "$CONDUCTOR_PODMAN_ROOT/storage" && "$4" == --runroot ]]
[[ "$5" == "$CONDUCTOR_PODMAN_ROOT/runroot" && ${#5} -le 50 ]]
[[ "$XDG_RUNTIME_DIR" =~ ^/tmp/cpr\.[[:alnum:]]{12}$ ]]
[[ "$XDG_RUNTIME_DIR" == "$(cat "$CONDUCTOR_PODMAN_ROOT/runtime-path")" ]]
[[ "$CONTAINERS_STORAGE_CONF" == "$CONDUCTOR_PODMAN_ROOT/storage.conf" ]]
case "$6" in
  info) printf '%s\n' "$5" ;;
  system) [[ "$7" == reset && "$8" == --force ]] ;;
  *) exit 1 ;;
esac
STUB
chmod 700 "$fixture/bin/podman"
export PATH="$fixture/bin:$PATH"
export RUNNER_TEMP="$fixture/estate-actions-runner-with-a-path-longer-than-fifty-characters/_work/_temp"
export GITHUB_RUN_ID=123456789012 GITHUB_RUN_ATTEMPT=1 GITHUB_JOB=build_container_arm64
wrapper="$(dirname "$0")/ci-podman.sh"
for i in 1 2; do
  export GITHUB_ENV="$fixture/env-$i"
  bash "$wrapper" --prepare >"$fixture/output-$i"
  set -a
  # The wrapper writes only the controlled fixture's environment assignments.
  # shellcheck disable=SC1090
  source "$GITHUB_ENV"
  set +a
  runtime_roots+=("$CONDUCTOR_PODMAN_ROOT")
  network_roots+=("$XDG_RUNTIME_DIR")
  [[ "$(stat -c %a "$CONDUCTOR_PODMAN_ROOT")" == 700 ]]
  [[ "$(stat -c %a "$XDG_RUNTIME_DIR")" == 700 ]]
  [[ "$(cat "$fixture/output-$i")" == "$CONDUCTOR_PODMAN_ROOT/runroot" ]]
done
[[ "${runtime_roots[0]}" != "${runtime_roots[1]}" ]]
[[ "${network_roots[0]}" != "${network_roots[1]}" ]]
bash "$wrapper" --cleanup
[[ ! -e "${runtime_roots[1]}" && -d "${runtime_roots[0]}" ]]
[[ ! -e "${network_roots[1]}" && -d "${network_roots[0]}" ]]
CONDUCTOR_PODMAN_ROOT="$fixture" bash "$wrapper" --cleanup && exit 1
[[ -d "$fixture" ]]
CONDUCTOR_PODMAN_ROOT="${runtime_roots[0]}" \
  CONTAINERS_STORAGE_CONF="${runtime_roots[0]}/storage.conf" \
  XDG_RUNTIME_DIR="${network_roots[1]}" bash "$wrapper" --cleanup && exit 1
[[ -d "${network_roots[0]}" && -d "${runtime_roots[0]}" ]]
printf 'Long runner paths, job isolation and scoped cleanup passed\n'
