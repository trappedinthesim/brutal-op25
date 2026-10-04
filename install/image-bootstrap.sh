#!/usr/bin/env bash
# Source from host launchers only. Never store credentials in the image.
BRUTAL_LOCAL_IMAGE=brutal-op25:0.3.0-dev.6

brutal_release_reference() {
    local task_release_image
    task_release_image=$(tr -d '\r\n' < "$1/build/image-release.txt")
    [[ "$task_release_image" =~ ^ghcr\.io/trappedinthesim/brutal-op25-receiver:[a-zA-Z0-9._-]+$ ]] || {
        printf '%s\n' 'Invalid release-image reference. No image was pulled or built.' >&2
        return 1
    }
    printf '%s\n' "$task_release_image"
}

brutal_update_base_image() {
    local task_root=$1 task_release_image task_old_id task_new_id
    task_release_image=$(brutal_release_reference "$task_root") || return 1
    printf 'Checking release image: %s\n' "$task_release_image"
    # A failed pull must never replace the user's known-working local image.
    docker pull "$task_release_image" || {
        printf '%s\n' 'Release image could not be fetched. The current image was left unchanged.' >&2
        return 1
    }
    task_old_id=$(docker image inspect "$BRUTAL_LOCAL_IMAGE" --format '{{.Id}}' 2>/dev/null || true)
    task_new_id=$(docker image inspect "$task_release_image" --format '{{.Id}}') || return 1
    if [[ $task_old_id == "$task_new_id" ]]; then
        printf '%s\n' 'Already running this release image.'
        return 0
    fi
    if [[ -n $task_old_id ]]; then
        docker tag "$BRUTAL_LOCAL_IMAGE" "${BRUTAL_LOCAL_IMAGE}-previous" || return 1
    fi
    docker tag "$task_release_image" "$BRUTAL_LOCAL_IMAGE" || return 1
    printf 'Updated image ready. Previous image: %s-previous\n' "$BRUTAL_LOCAL_IMAGE"
}

brutal_rollback_base_image() {
    docker image inspect "${BRUTAL_LOCAL_IMAGE}-previous" >/dev/null 2>&1 || {
        printf '%s\n' 'No previous image is available for rollback.' >&2
        return 1
    }
    docker tag "$BRUTAL_LOCAL_IMAGE" "${BRUTAL_LOCAL_IMAGE}-failed" || return 1
    docker tag "${BRUTAL_LOCAL_IMAGE}-previous" "$BRUTAL_LOCAL_IMAGE" || return 1
    printf '%s\n' 'Previous image restored. Saved systems were not changed.'
}

brutal_sdrplay_addon_current() {
    local task_base_id task_addon_base_id
    task_base_id=$(docker image inspect "$BRUTAL_LOCAL_IMAGE" --format '{{.Id}}' 2>/dev/null) || return 1
    task_addon_base_id=$(docker image inspect "$1" --format '{{index .Config.Labels "io.brutal-op25.base-image-id"}}' 2>/dev/null) || return 1
    [[ $task_base_id == "$task_addon_base_id" ]]
}

brutal_ensure_base_image() {
    local task_root=$1
    local task_force_build=${2:-false}
    local task_release_image
    if [[ "$task_force_build" != true ]] && docker image inspect "$BRUTAL_LOCAL_IMAGE" >/dev/null 2>&1; then
        return 0
    fi
    if [[ "$task_force_build" != true ]]; then
        task_release_image=$(brutal_release_reference "$task_root") || return 1
        printf 'Fetching prebuilt Brutal OP25 image: %s\n' "$task_release_image"
        if docker pull "$task_release_image" && docker tag "$task_release_image" "$BRUTAL_LOCAL_IMAGE"; then
            printf '%s\n' 'Prebuilt image ready. No OP25 compilation needed on this computer.'
            return 0
        fi
        printf '%s\n' 'The prebuilt image is unavailable or still private. Building from this repository instead.'
    fi
    docker build --file "$task_root/build/Dockerfile" --tag "$BRUTAL_LOCAL_IMAGE" "$task_root"
}
