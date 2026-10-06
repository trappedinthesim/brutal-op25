#!/usr/bin/env bash
# Export or restore saved systems without putting the Docker socket in a container.
set -euo pipefail
[[ $# == 2 && ( $1 == export || $1 == restore ) ]] || {
    printf '%s\n' 'Usage: bash install/profile-data.sh export|restore /absolute/path.zip' >&2
    exit 2
}
task_action=$1
task_path=$2
[[ $task_path == /* && $task_path == *.zip ]] || {
    printf '%s\n' 'Use an absolute .zip path for the saved-systems backup.' >&2
    exit 2
}
task_parent=$(dirname -- "$task_path")
task_name=$(basename -- "$task_path")
[[ $task_name != . && $task_name != .. ]] || exit 2
if [[ $task_action == export ]]; then
    mkdir -p -- "$task_parent"
else
    [[ -f $task_path ]] || { printf '%s\n' 'Backup file not found.' >&2; exit 1; }
fi
task_parent=$(cd -- "$task_parent" && pwd -P)
task_image=${BRUTAL_OP25_IMAGE:-brutal-op25:0.3.0-dev.20}
task_volume=${BRUTAL_PROFILE_VOLUME:-brutal-op25-data}
[[ $task_volume =~ ^brutal-op25-(data|test-[a-z0-9]+)$ ]] || {
    printf '%s\n' 'Invalid saved-system volume name.' >&2; exit 2;
}
task_docker=(docker)
if ! docker info >/dev/null 2>&1; then
    command -v sudo >/dev/null || { printf '%s\n' 'Docker access needs sudo.' >&2; exit 1; }
    sudo -v
    task_docker=(sudo docker)
fi
"${task_docker[@]}" image inspect "$task_image" >/dev/null 2>&1 || {
    printf '%s\n' 'Brutal OP25 image is missing. Run setup once before backup or restore.' >&2
    exit 1
}
task_mount_mode=rw
if [[ $task_action == restore ]]; then task_mount_mode=ro; fi
"${task_docker[@]}" run --rm --network none --read-only --user 0:0 \
    --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE \
    --volume "$task_volume:/data" \
    --volume "$task_parent:/transfer:$task_mount_mode" \
    --entrypoint python "$task_image" \
    profile_transfer.py "$task_action" "/transfer/$task_name"
if [[ $task_action == export && ${task_docker[0]} == sudo ]]; then
    sudo chown "$(id -u):$(id -g)" -- "$task_path"
fi
