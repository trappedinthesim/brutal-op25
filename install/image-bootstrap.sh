#!/usr/bin/env bash
# Source from host launchers only. Never store credentials in the image.
BRUTAL_LOCAL_IMAGE=brutal-op25:0.3.0-dev.24

brutal_release_reference() {
    local task_release_image
    task_release_image=$(tr -d '\r\n' < "$1/build/image-release.txt")
    [[ "$task_release_image" =~ ^ghcr\.io/trappedinthesim/brutal-op25-receiver:[a-zA-Z0-9._-]+$ ]] || {
        printf '%s\n' 'Invalid release-image reference. No image was pulled or built.' >&2
        return 1
    }
    printf '%s\n' "$task_release_image"
}

brutal_image_user_ready() {
    # Use the same numeric identity as the receiver so Docker does not need to
    # resolve a username before mounting the container filesystem. id still
    # verifies that UID 1000 resolves to op25 inside that filesystem.
    local task_user
    BRUTAL_IMAGE_ACCOUNT_MISSING=0
    if ! task_user=$(docker run --rm --network none --read-only --cap-drop ALL \
        --security-opt no-new-privileges:true --user 1000:1000 \
        --env LC_ALL=C --entrypoint /usr/bin/id "$1" -un 2>&1); then
        printf '%s\n' "$task_user" >&2
        if [[ $task_user == *'cannot find name for user ID 1000'* ]]; then
            BRUTAL_IMAGE_ACCOUNT_MISSING=1
        fi
        return 1
    fi
    [[ $task_user == op25 ]] || {
        printf 'Receiver image account check failed: expected op25 for UID 1000, got %s.\n' "$task_user" >&2
        return 1
    }
}

brutal_verify_release_image() {
    local task_release=$1
    if brutal_image_user_ready "$task_release"; then return 0; fi
    # Only the observed missing-account failure warrants replacing cached image
    # files. Permission, daemon, network, and other runtime errors do not.
    [[ ${BRUTAL_IMAGE_ACCOUNT_MISSING:-0} == 1 ]] || return 1
    brutal_replace_broken_cached_image "$task_release" || return 1
    if ! brutal_image_user_ready "$task_release"; then
        printf '%s\n' 'The receiver still fails after one cache replacement. Docker storage needs diagnosis; automatic repair will not loop. Saved systems are untouched.' >&2
        return 1
    fi
}

brutal_replace_broken_cached_image() {
    local task_release=$1 task_id task_source task_refs task_ref task_containers task_current
    local task_found=0
    local -a task_tags=()
    [[ $task_release =~ ^ghcr\.io/trappedinthesim/brutal-op25-receiver:[a-zA-Z0-9._-]+$ ]] || return 1
    task_id=$(docker image inspect "$task_release" --format '{{.Id}}') || return 1
    [[ $task_id =~ ^sha256:[a-f0-9]{64}$ ]] || return 1
    task_source=$(docker image inspect "$task_id" --format '{{index .Config.Labels "org.opencontainers.image.source"}}') || return 1
    [[ $task_source == https://github.com/trappedinthesim/brutal-op25 ]] || {
        printf '%s\n' 'Cache repair stopped: image ownership could not be verified.' >&2; return 1;
    }
    task_containers=$(docker ps -aq --filter "ancestor=$task_id") || return 1
    [[ -z $task_containers ]] || {
        printf '%s\n' 'Cache repair stopped: a container still references this image. Close Brutal OP25 and check its remaining containers before retrying. No containers or saved systems were removed.' >&2; return 1;
    }
    task_refs=$(docker image inspect "$task_id" --format '{{range .RepoDigests}}{{println .}}{{end}}') || return 1
    while IFS= read -r task_ref; do
        [[ -n $task_ref ]] || continue
        [[ $task_ref =~ ^ghcr\.io/trappedinthesim/brutal-op25-receiver@sha256:[a-f0-9]{64}$ ]] || {
            printf '%s\n' 'Cache repair stopped: this image also belongs to another registry repository.' >&2; return 1;
        }
    done <<< "$task_refs"
    task_refs=$(docker image inspect "$task_id" --format '{{range .RepoTags}}{{println .}}{{end}}') || return 1
    while IFS= read -r task_ref; do
        [[ -n $task_ref ]] || continue
        if [[ ! $task_ref =~ ^brutal-op25:[0-9]+\.[0-9]+\.[0-9]+(-dev\.[0-9]+)?(-(previous|failed))?$ &&
              ! $task_ref =~ ^ghcr\.io/trappedinthesim/brutal-op25-receiver:[a-zA-Z0-9._-]+$ ]]; then
            printf '%s\n' 'Cache repair stopped: this image has a tag outside the managed Brutal OP25 images.' >&2; return 1
        fi
        [[ $task_ref != "$task_release" ]] || task_found=1
        task_tags+=("$task_ref")
    done <<< "$task_refs"
    ((task_found && ${#task_tags[@]})) || return 1
    # Check all references before removing any. Never force removal or prune
    # Docker globally, and never mount/delete saved-system volumes here.
    for task_ref in "${task_tags[@]}"; do
        task_current=$(docker image inspect "$task_ref" --format '{{.Id}}') || return 1
        [[ $task_current == "$task_id" ]] || {
            printf '%s\n' 'Cache repair stopped: image tags changed during validation. Retry when no other update is running.' >&2; return 1;
        }
    done
    printf '%s\n' 'Replacing the failed Brutal OP25 image cache. This may download the receiver again; saved systems stay in their separate data volume.'
    docker image rm --no-prune "${task_tags[@]}" || {
        printf '%s\n' 'Docker could not remove the failed image cache. No forced cleanup was attempted.' >&2; return 1;
    }
    if docker image inspect "$task_id" >/dev/null 2>&1; then
        printf '%s\n' 'Docker still retains the failed image. Cache repair needs further diagnosis.' >&2; return 1
    fi
    docker pull "$task_release" || {
        printf '%s\n' 'The failed cache was removed, but downloading its replacement failed. Run Update again when the connection is available. Saved systems are untouched.' >&2; return 1;
    }
}

brutal_update_base_image() {
    local task_root=$1 task_release_image task_old_id task_new_id task_previous_tag task_previous_id
    task_release_image=$(brutal_release_reference "$task_root") || return 1
    printf 'Checking release image: %s\n' "$task_release_image"
    # A failed pull must never replace the user's known-working local image.
    docker pull "$task_release_image" || {
        printf '%s\n' 'Release image could not be fetched. The current image was left unchanged.' >&2
        return 1
    }
    brutal_verify_release_image "$task_release_image" || {
        printf '%s\n' 'Receiver image validation failed; see the specific failure above. Saved systems were not changed.' >&2
        return 1
    }
    task_old_id=$(docker image inspect "$BRUTAL_LOCAL_IMAGE" --format '{{.Id}}' 2>/dev/null || true)
    task_new_id=$(docker image inspect "$task_release_image" --format '{{.Id}}') || return 1
    # A program update may have already fetched the new version during
    # --prepare-only. Recover the older version-specific tag in that case.
    if [[ $task_old_id == "$task_new_id" || -z $task_old_id ]]; then
        task_previous_tag=$(brutal_find_previous_base_image)
        if [[ -n $task_previous_tag ]]; then
            task_previous_id=$(docker image inspect "$task_previous_tag" --format '{{.Id}}' 2>/dev/null || true)
            if [[ -n $task_previous_id && $task_previous_id != "$task_new_id" ]]; then
                docker tag "$task_previous_tag" "${BRUTAL_LOCAL_IMAGE}-previous" || return 1
            fi
        fi
    fi
    if [[ $task_old_id == "$task_new_id" ]]; then
        printf '%s\n' 'Already running this release image.'
        brutal_prune_old_base_image_tags "$task_release_image"
        return 0
    fi
    if [[ -n $task_old_id ]]; then
        docker tag "$BRUTAL_LOCAL_IMAGE" "${BRUTAL_LOCAL_IMAGE}-previous" || return 1
    fi
    docker tag "$task_release_image" "$BRUTAL_LOCAL_IMAGE" || return 1
    printf 'Updated image ready. Previous image: %s-previous\n' "$BRUTAL_LOCAL_IMAGE"
    brutal_prune_old_base_image_tags "$task_release_image"
}

brutal_find_previous_base_image() {
    local task_tag
    while IFS= read -r task_tag; do
        [[ $task_tag != "$BRUTAL_LOCAL_IMAGE" &&
           $task_tag =~ ^brutal-op25:[0-9]+\.[0-9]+\.[0-9]+(-dev\.[0-9]+)?$ ]] || continue
        printf '%s\n' "$task_tag"
    done < <(docker image ls --format '{{.Repository}}:{{.Tag}}' --filter 'reference=brutal-op25:*') |
        sort -V | tail -n 1
}

brutal_prune_old_base_image_tags() {
    local task_release_image=$1 task_tag task_keep_addon task_source
    # Only remove tags owned by this receiver. No global docker image prune:
    # other apps and saved-system volumes stay put. Keep the newest locally
    # built SDRplay addon as well; an older base image may need that rollback.
    task_keep_addon=$(
        docker image ls --format '{{.Repository}}:{{.Tag}}' --filter 'reference=brutal-op25-sdrplay:*' |
            grep -E '^brutal-op25-sdrplay:[0-9]+\.[0-9]+\.[0-9]+(-dev\.[0-9]+)?-local$' |
            sort -V | tail -n 1 || true
    )
    while IFS= read -r task_tag; do
        [[ $task_tag != "$BRUTAL_LOCAL_IMAGE" &&
           $task_tag != "${BRUTAL_LOCAL_IMAGE}-previous" &&
           $task_tag != "$task_release_image" &&
           $task_tag != "$task_keep_addon" ]] || continue
        if [[ $task_tag =~ ^brutal-op25:[0-9]+\.[0-9]+\.[0-9]+(-dev\.[0-9]+)?(-(previous|failed))?$ ||
              $task_tag =~ ^ghcr\.io/trappedinthesim/brutal-op25-receiver:[0-9]+\.[0-9]+\.[0-9]+(-dev\.[0-9]+)?$ ||
              $task_tag =~ ^brutal-op25-sdrplay:[0-9]+\.[0-9]+\.[0-9]+(-dev\.[0-9]+)?-local$ ]]; then
            task_source=$(docker image inspect "$task_tag" --format '{{index .Config.Labels "org.opencontainers.image.source"}}' 2>/dev/null || true)
            [[ $task_source == https://github.com/trappedinthesim/brutal-op25 ]] || continue
            docker image rm "$task_tag" >/dev/null 2>&1 ||
                printf 'Could not remove old Brutal OP25 image tag %s (it may be in use).\n' "$task_tag" >&2
        fi
    done < <(docker image ls --format '{{.Repository}}:{{.Tag}}')
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
        if brutal_image_user_ready "$BRUTAL_LOCAL_IMAGE"; then return 0; fi
        printf '%s\n' 'The local receiver image failed its startup check. Checking the official release; saved systems are untouched.' >&2
    fi
    if [[ "$task_force_build" != true ]]; then
        task_release_image=$(brutal_release_reference "$task_root") || return 1
        printf 'Fetching prebuilt Brutal OP25 image: %s\n' "$task_release_image"
        if ! docker pull "$task_release_image"; then
            printf '%s\n' 'Could not download the prebuilt receiver image. Check your connection and retry; no local build was started.' >&2
            return 1
        fi
        brutal_verify_release_image "$task_release_image" || {
            printf '%s\n' 'Receiver image validation failed; see the specific failure above. Saved systems were not changed.' >&2
            return 1
        }
        docker tag "$task_release_image" "$BRUTAL_LOCAL_IMAGE" || {
            printf '%s\n' 'Downloaded the receiver image but could not activate it locally. Check Docker storage and retry.' >&2
            return 1
        }
        printf '%s\n' 'Prebuilt image ready. No OP25 compilation needed on this computer.'
        return 0
    fi
    docker build --file "$task_root/build/Dockerfile" --tag "$BRUTAL_LOCAL_IMAGE" "$task_root"
}
