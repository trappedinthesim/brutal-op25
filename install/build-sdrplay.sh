#!/usr/bin/env bash
# Private local addon only; explicit license acceptance, never publish automatically.
set -euo pipefail
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
task_package=${1:?Supply the official SDRplay Linux 3.15.2 installer path}
task_base=${BRUTAL_OP25_BASE_IMAGE:-brutal-op25:0.3.0-dev.16}
task_addon=brutal-op25-sdrplay:0.3.0-dev.16-local
command -v docker >/dev/null
task_endpoint=${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}
[[ "$task_endpoint" == unix://* ]] || { printf '%s\n' 'Use a local Linux Docker socket for this private addon.' >&2; exit 1; }
[[ -f "$task_package" ]] || { printf '%s\n' 'Installer file not found.' >&2; exit 1; }
task_hash=$(sha256sum -- "$task_package")
[[ "${task_hash%% *}" == 3a97ca764263bbe76fb0f2220e6408942357e8864c19e1408a6d6987af382fe3 ]] || {
    printf '%s\n' 'Installer checksum mismatch. No software was installed.' >&2; exit 1;
}
docker image inspect "$task_base" >/dev/null
task_base_id=$(docker image inspect "$task_base" --format '{{.Id}}')
. "$task_root/install/sdrplay-license.sh"
brutal_request_sdrplay_license "$task_root/docs/SDRplay-EULA.txt" || exit 1
# Isolated vendor context: never send the installer parent directory to Docker.
task_context=$(mktemp -d /tmp/brutal-op25.XXXXXXXX)
trap 'rm -f -- "$task_context/SDRplay-API-Linux-official.download"; rmdir -- "$task_context"' EXIT
cp -- "$task_package" "$task_context/SDRplay-API-Linux-official.download"
docker build --file "$task_root/build/Dockerfile.sdrplay" \
    --build-context "sdrplay-api=$task_context" --build-arg "BASE_IMAGE=$task_base" \
    --build-arg "BRUTAL_BASE_IMAGE_ID=$task_base_id" \
    --build-arg SDRPLAY_LICENSE_ACCEPTED=yes --tag "$task_addon" "$task_root"
docker run --rm --network none --read-only --cap-drop ALL \
    --tmpfs /tmp --tmpfs /home/op25:uid=1000,gid=1000 \
    --entrypoint python "$task_addon" -c \
    'from hardware_check import check_profile; r=check_profile("rspdxr2"); assert r["software_dependencies_present"], r["missing"]' || {
    printf '%s\n' 'The local SDRplay addon built, but its API or Soapy driver did not load. No receiver was started.' >&2
    exit 1
}
printf '%s\n' 'Local addon built. Do not push it to a public registry.'
printf 'Start: BRUTAL_OP25_IMAGE=%s bash "%s/brutal-op25.sh"\n' "$task_addon" "$task_root"
