#!/usr/bin/env bash
# Maintainer reproduction of the bundled Windows helper. Not run by end users.
set -euo pipefail
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
task_api_dir=${SDRPLAY_WINDOWS_API_DIR:-/mnt/c/Program Files/SDRplay/API}
task_output=${1:-$task_root/rsp_tcp.exe}
[[ -f "$task_api_dir/x64/sdrplay_api.lib" && -f "$task_api_dir/inc/sdrplay_api.h" ]] || {
    printf '%s\n' 'The official SDRplay Windows API headers/import library are needed to rebuild.' >&2
    exit 1
}
cd -- "$task_root"
x86_64-w64-mingw32-gcc -O2 -static -Wl,--no-insert-timestamp -D_GNU_SOURCE \
    '-DSERVER_NAME="rsp_tcp"' '-DSERVER_VERSION="0.1"' \
    -I"$task_api_dir/inc" -I. \
    rsp_tcp.c getopt/getopt.c "$task_api_dir/x64/sdrplay_api.lib" \
    -lws2_32 -lpthread -o "$task_output"
sha256sum -- "$task_output"
