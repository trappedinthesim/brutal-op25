#!/usr/bin/env bash
set -euo pipefail

# Remove only resources identified as belonging to Brutal OP25. This script is
# deliberately separate from the Windows-folder cleanup so Docker failures
# cannot be mistaken for a successful full uninstall.
task_volume=brutal-op25-data
task_source=https://github.com/trappedinthesim/brutal-op25
if [[ ${1:-} != '' && ${1:-} != --check ]]; then
    printf '%s\n' 'Usage: uninstall-brutal-data.sh [--check]' >&2
    exit 2
fi

if ! docker info >/dev/null; then
    printf '%s\n' 'Docker Engine inside Ubuntu is unavailable. Start it, then retry uninstall; no program files were removed.' >&2
    exit 1
fi

if docker volume inspect "$task_volume" >/dev/null 2>&1; then
    task_users=$(docker ps -aq --filter "volume=$task_volume")
    if [[ -n $task_users ]]; then
        printf 'The saved-systems volume is still used by container(s): %s\n' "$task_users" >&2
        printf '%s\n' 'Stop and remove those Brutal OP25 containers before uninstalling.' >&2
        exit 1
    fi
fi

task_tags=()
task_listing=$(docker image ls --format '{{.Repository}}:{{.Tag}}')
while IFS= read -r task_tag; do
    [[ $task_tag =~ ^brutal-op25:[0-9]+\.[0-9]+\.[0-9]+(-dev\.[0-9]+)?(-(previous|failed))?$ ||
       $task_tag =~ ^brutal-op25-sdrplay:[0-9]+\.[0-9]+\.[0-9]+(-dev\.[0-9]+)?-local$ ||
       $task_tag =~ ^ghcr\.io/trappedinthesim/brutal-op25-receiver:[0-9]+\.[0-9]+\.[0-9]+(-dev\.[0-9]+)?$ ]] || continue
    task_label=$(docker image inspect "$task_tag" --format '{{index .Config.Labels "org.opencontainers.image.source"}}')
    if [[ $task_label != "$task_source" ]]; then
        printf 'Refusing to remove unverified image tag: %s\n' "$task_tag" >&2
        exit 1
    fi
    task_users=$(docker ps -aq --filter "ancestor=$task_tag")
    if [[ -n $task_users ]]; then
        printf 'Image %s is still used by container(s): %s\n' "$task_tag" "$task_users" >&2
        printf '%s\n' 'Stop and remove those containers before uninstalling.' >&2
        exit 1
    fi
    task_tags+=("$task_tag")
done <<< "$task_listing"

if [[ ${1:-} == --check ]]; then
    if docker volume inspect "$task_volume" >/dev/null 2>&1; then
        printf 'Would delete saved-systems volume: %s\n' "$task_volume"
    fi
    printf 'Would remove %s verified Brutal OP25 image tag(s).\n' "${#task_tags[@]}"
    exit 0
fi

for task_tag in "${task_tags[@]}"; do
    docker image rm "$task_tag"
done
printf 'Removed %s Brutal OP25 image tag(s).\n' "${#task_tags[@]}"

if docker volume inspect "$task_volume" >/dev/null 2>&1; then
    docker volume rm "$task_volume"
    printf '%s\n' 'Deleted Brutal OP25 saved systems and settings volume.'
fi
