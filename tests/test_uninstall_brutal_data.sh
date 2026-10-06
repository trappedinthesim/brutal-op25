#!/usr/bin/env bash
set -euo pipefail

task_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
task_tmp=$(mktemp -d /tmp/brutal-uninstall-test.XXXXXXXX)
trap '[[ $task_tmp == /tmp/brutal-uninstall-test.* ]] && rm -rf -- "$task_tmp"' EXIT
export MOCK_DOCKER_DIR=$task_tmp

docker() {
    printf '%s\n' "$*" >> "$MOCK_DOCKER_DIR/calls"
    case "$1 ${2-}" in
        'info '*) return 0 ;;
        'volume inspect') [[ -f $MOCK_DOCKER_DIR/volume ]] ;;
        'volume rm') rm -- "$MOCK_DOCKER_DIR/volume" ;;
        'ps -aq')
            if [[ -f $MOCK_DOCKER_DIR/block-volume && $* == *volume=* ]] ||
               [[ -f $MOCK_DOCKER_DIR/block-image && $* == *ancestor=* ]]; then
                printf '%s\n' abc123
            fi ;;
        'image ls') cat "$MOCK_DOCKER_DIR/tags" ;;
        'image inspect')
            if [[ -f $MOCK_DOCKER_DIR/bad-label ]]; then
                printf '%s\n' 'https://example.invalid/other'
            else
                printf '%s\n' 'https://github.com/trappedinthesim/brutal-op25'
            fi ;;
        'image rm') printf '%s\n' "$3" >> "$MOCK_DOCKER_DIR/removed-tags" ;;
        *) printf 'Unexpected mocked Docker command: %s\n' "$*" >&2; return 99 ;;
    esac
}
export -f docker

printf '%s\n' 'brutal-op25:0.3.0-dev.19' \
    'ghcr.io/trappedinthesim/brutal-op25-receiver:0.3.0-dev.19' \
    'unrelated:latest' > "$task_tmp/tags"
touch "$task_tmp/volume" "$task_tmp/block-volume"
if bash "$task_root/install/uninstall-brutal-data.sh" > "$task_tmp/out" 2>&1; then
    echo 'Uninstall ignored a container using the data volume.' >&2; exit 1
fi
[[ -f $task_tmp/volume && ! -f $task_tmp/removed-tags ]]
rm -- "$task_tmp/block-volume"
touch "$task_tmp/bad-label"
if bash "$task_root/install/uninstall-brutal-data.sh" > "$task_tmp/out" 2>&1; then
    echo 'Uninstall accepted an image with an unverified source label.' >&2; exit 1
fi
[[ -f $task_tmp/volume && ! -f $task_tmp/removed-tags ]]
rm -- "$task_tmp/bad-label"
touch "$task_tmp/block-image"
if bash "$task_root/install/uninstall-brutal-data.sh" > "$task_tmp/out" 2>&1; then
    echo 'Uninstall ignored a container using an app image.' >&2; exit 1
fi
[[ -f $task_tmp/volume && ! -f $task_tmp/removed-tags ]]
rm -- "$task_tmp/block-image"
bash "$task_root/install/uninstall-brutal-data.sh" --check > "$task_tmp/out" 2>&1
[[ -f $task_tmp/volume && ! -f $task_tmp/removed-tags ]]
bash "$task_root/install/uninstall-brutal-data.sh" > "$task_tmp/out" 2>&1
[[ ! -f $task_tmp/volume ]]
[[ $(wc -l < "$task_tmp/removed-tags") -eq 2 ]]
! grep -q 'unrelated:latest' "$task_tmp/removed-tags"
echo 'Scoped Docker uninstall tests passed.'
