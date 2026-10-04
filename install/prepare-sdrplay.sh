#!/usr/bin/env bash
# Download and build the private SDRplay addon for a selected RSPdx-R2.
set -euo pipefail
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
task_expected=3a97ca764263bbe76fb0f2220e6408942357e8864c19e1408a6d6987af382fe3
task_page=https://sdrplay.com/download/hardware-api-linux/
if ! command -v curl >/dev/null; then
    command -v apt-get >/dev/null || { printf '%s\n' 'SDRplay setup needs curl and this host has no apt installer.' >&2; exit 1; }
    printf '%s\n' 'The SDRplay download needs curl, which is not installed.'
    read -r -p 'Install curl using the system package manager? [y/N]: ' task_consent
    [[ "$task_consent" == y || "$task_consent" == Y ]] || exit 1
    if ((EUID == 0)); then apt-get update && apt-get install -y curl
    elif command -v sudo >/dev/null; then sudo apt-get update && sudo apt-get install -y curl
    else printf '%s\n' 'Installing curl needs sudo.' >&2; exit 1
    fi
fi
command -v sha256sum >/dev/null || { printf '%s\n' 'SDRplay setup needs sha256sum.' >&2; exit 1; }
task_context=$(mktemp -d /tmp/brutal-sdrplay.XXXXXXXX)
task_package="$task_context/SDRplay-API-Linux-official.download"
trap 'rm -f -- "$task_package"; rmdir -- "$task_context"' EXIT
printf '%s\n' 'Downloading the official SDRplay Linux API for a private local addon.'
task_html=$(curl --fail --silent --show-error --location --max-time 30 "$task_page")
task_url=$(printf '%s' "$task_html" | sed -n 's/.*data-downloadurl="\([^"]*\)".*/\1/p' | head -n 1)
[[ "$task_url" == "${task_page}?"* ]] || {
    printf '%s\n' 'SDRplay changed its download page; refusing an unverified download.' >&2; exit 1;
}
curl --fail --silent --show-error --location --max-time 180 --output "$task_package" "$task_url"
task_hash=$(sha256sum -- "$task_package")
[[ "${task_hash%% *}" == "$task_expected" ]] || {
    printf '%s\n' 'SDRplay installer checksum mismatch. Nothing was executed or installed.' >&2; exit 1;
}
bash "$task_root/install/build-sdrplay.sh" "$task_package"
