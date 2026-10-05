#!/usr/bin/env bash
# Native Linux first-run installer and returning-user entrypoint.
set -euo pipefail

task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
task_check_only=false
task_prepare_only=false
task_update_only=false
task_rollback_image=false
task_backup=false
task_restore_path=''
while (($#)); do
    case "$1" in
        --check) task_check_only=true ;;
        --prepare-only) task_prepare_only=true ;;
        --update-image) task_update_only=true ;;
        --rollback-image) task_rollback_image=true ;;
        --backup) task_backup=true ;;
        --restore) shift; task_restore_path=${1:?Supply the full backup ZIP path} ;;
        --help)
            printf '%s\n' 'Usage: bash install-brutal-op25.sh [--check | --prepare-only | --update-image | --rollback-image | --backup | --restore /path.zip]' \
                'Installs missing native-Linux Docker Engine only after your approval, builds OP25, then opens radio setup.' \
                'Windows WSL uses the same Linux engine with a guided USB bridge. --check changes nothing.'
            exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

if [[ ! -f /.dockerenv ]] && grep -qi microsoft /proc/sys/kernel/osrelease && [[ ${BRUTAL_WSL_NATIVE:-} != 1 ]]; then
    if "$task_backup" || [[ -n $task_restore_path ]]; then
        export BRUTAL_WSL_NATIVE=1 DOCKER_HOST=unix:///var/run/docker.sock
    else
    if "$task_check_only"; then exec bash "$task_root/install/brutal-wsl.sh" --check; fi
    if "$task_prepare_only"; then exec bash "$task_root/install/brutal-wsl.sh" --prepare-only; fi
    if "$task_update_only"; then exec bash "$task_root/install/brutal-wsl.sh" --update-image; fi
    if "$task_rollback_image"; then exec bash "$task_root/install/brutal-wsl.sh" --rollback-image; fi
    exec bash "$task_root/install/brutal-wsl.sh"
    fi
fi

[[ $(uname -m) == x86_64 ]] || {
    printf '%s\n' 'This release is validated for x86_64 Linux only. Other architectures need an image build and hardware validation.' >&2
    exit 1
}

task_as_root() {
    if ((EUID == 0)); then "$@"
    else sudo -- "$@"
    fi
}

task_use_sudo=false
task_docker() {
    if "$task_use_sudo"; then sudo docker "$@"
    else docker "$@"
    fi
}

if "$task_check_only"; then
    printf 'Docker command: %s\n' "$(command -v docker || printf 'missing')"
    if command -v docker >/dev/null && docker info --format '{{.OSType}}' >/dev/null 2>&1; then
        printf '%s\n' 'Docker Engine: available to this user'
    else
        printf '%s\n' 'Docker Engine: missing, stopped, or requires sudo'
    fi
    printf '%s\n' 'No packages, services, USB permissions, or images were changed.'
    exit 0
fi

. "$task_root/install/user-launcher.sh"
if [[ ${BRUTAL_WSL_NATIVE:-} != 1 ]]; then
    brutal_install_user_command "$task_root"
fi

task_docker_command=$(command -v docker || true)
# WSL inherits Windows PATH. A Windows Docker CLI (including a Desktop stub)
# is not a Linux Engine installation, even if `command -v docker` finds it.
if grep -qi microsoft /proc/sys/kernel/osrelease && [[ $task_docker_command == /mnt/* ]]; then
    task_docker_command=''
fi
if [[ -z $task_docker_command ]]; then
    . /etc/os-release
    case "${ID:-}:${VERSION_ID:-}" in
        ubuntu:22.04|ubuntu:24.04|ubuntu:26.04|debian:12|debian:13) ;;
        *) printf '%s\n' 'Automatic Docker Engine installation supports official Ubuntu 22.04/24.04/26.04 and Debian 12/13 only.' \
            'For this host, install a local Linux Docker Engine from its official instructions, then rerun this installer.' >&2; exit 1 ;;
    esac
    command -v apt-get >/dev/null && command -v dpkg-query >/dev/null || {
        printf '%s\n' 'Apt and dpkg are required for the guided Docker Engine installation.' >&2; exit 1;
    }
    if ((EUID != 0)); then command -v sudo >/dev/null || {
        printf '%s\n' 'Docker Engine installation needs sudo. Ask the system administrator to install Docker Engine, then rerun.' >&2; exit 1;
    }; fi
    task_conflicts=()
    for task_package in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc; do
        if [[ $(dpkg-query -W -f='${Status}' "$task_package" 2>/dev/null || true) == 'install ok installed' ]]; then
            task_conflicts+=("$task_package")
        fi
    done
    if ((${#task_conflicts[@]})); then
        printf 'Existing packages need an administrator decision before Docker Engine can be installed: %s\n' "${task_conflicts[*]}" >&2
        printf '%s\n' 'Nothing was removed. See https://docs.docker.com/engine/install/ for the conflict guidance.' >&2
        exit 1
    fi
    task_source=/etc/apt/sources.list.d/docker.sources
    if [[ -e "$task_source" ]]; then
        grep -Fxq "URIs: https://download.docker.com/linux/$ID" "$task_source" || {
            printf 'Existing %s is not the expected official Docker repository; refusing to overwrite it.\n' "$task_source" >&2; exit 1;
        }
    fi
    task_codename=${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}
    [[ "$task_codename" =~ ^[a-z]+$ ]] || { printf '%s\n' 'Cannot determine a supported distro codename.' >&2; exit 1; }
    printf '%s\n' "Docker Engine is missing. Setup can add Docker Inc.'s official apt repository and install its engine." \
        'This starts a system service and may change firewall behavior. It will not add your user to the root-equivalent docker group.'
    task_consent=${BRUTAL_DOCKER_INSTALL_ACCEPTED:-}
    if [[ $task_consent != 1 ]]; then
        read -r -p 'Install Docker Engine and continue? [y/N]: ' task_consent
    fi
    [[ "$task_consent" == 1 || "$task_consent" == y || "$task_consent" == Y ]] || {
        printf '%s\n' 'Docker installation declined. Nothing was installed by this step.'; exit 1;
    }
    task_as_root apt-get update
    task_as_root apt-get install -y ca-certificates curl
    task_as_root install -m 0755 -d /etc/apt/keyrings
    task_as_root curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
    task_as_root chmod a+r /etc/apt/keyrings/docker.asc
    if [[ ! -e "$task_source" ]]; then
        task_arch=$(dpkg --print-architecture)
        printf 'Types: deb\nURIs: https://download.docker.com/linux/%s\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' \
            "$ID" "$task_codename" "$task_arch" | task_as_root tee "$task_source" >/dev/null
    fi
    task_as_root apt-get update
    task_as_root apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

if ! docker info --format '{{.OSType}}' >/dev/null 2>&1; then
    if ((EUID != 0)); then
        command -v sudo >/dev/null || { printf '%s\n' 'Docker access needs sudo or an administrator.' >&2; exit 1; }
        printf '%s\n' 'Docker access needs one sudo approval. Setup will not add you to the root-equivalent docker group.'
        sudo -v
        task_use_sudo=true
    fi
    if ! task_docker info --format '{{.OSType}}' >/dev/null 2>&1; then
        printf '%s\n' 'Starting the local Docker service.'
        if command -v systemctl >/dev/null && [[ $(cat /proc/1/comm) == systemd ]]; then
            task_as_root systemctl start docker
        elif command -v service >/dev/null; then
            task_as_root service docker start
        fi
    fi
fi
task_engine=$(task_docker info --format '{{.OSType}}' 2>/dev/null) || {
    printf '%s\n' 'Docker Engine is installed but not ready. Check the service and rerun; no profile was changed.' >&2; exit 1;
}
[[ "$task_engine" == linux ]] || { printf '%s\n' 'A local Linux Docker Engine is required.' >&2; exit 1; }
task_endpoint=${DOCKER_HOST:-$(task_docker context inspect --format '{{.Endpoints.docker.Host}}')}
[[ "$task_endpoint" == unix://* ]] || {
    printf '%s\n' 'This launcher requires a local Linux Docker socket; a remote Docker context cannot access this computer radio.' >&2; exit 1;
}
. "$task_root/install/image-bootstrap.sh"

if "$task_update_only" || "$task_rollback_image"; then
    if "$task_use_sudo"; then
        if "$task_update_only"; then
            exec sudo -- env "BRUTAL_LOCAL_IMAGE=$BRUTAL_LOCAL_IMAGE" bash -c '. "$1/install/image-bootstrap.sh"; brutal_update_base_image "$1"' _ "$task_root"
        fi
        exec sudo -- env "BRUTAL_LOCAL_IMAGE=$BRUTAL_LOCAL_IMAGE" bash -c '. "$1/install/image-bootstrap.sh"; brutal_rollback_base_image' _ "$task_root"
    fi
    if "$task_update_only"; then brutal_update_base_image "$task_root"
    else brutal_rollback_base_image
    fi
    exit 0
fi

if "$task_backup" || [[ -n $task_restore_path ]]; then
    task_transfer_action=export
    task_transfer_path="$HOME/.local/share/brutal-op25/backups/systems-$(date -u +%Y%m%d-%H%M%S).zip"
    if [[ -n $task_restore_path ]]; then
        task_transfer_action=restore
        task_transfer_path=$task_restore_path
    fi
    bash "$task_root/install/profile-data.sh" "$task_transfer_action" "$task_transfer_path"
    if "$task_backup"; then printf 'Saved-system backup: %s\n' "$task_transfer_path"; fi
    exit 0
fi

if "$task_prepare_only"; then
    if "$task_use_sudo"; then
        sudo -- bash -c '. "$1/install/image-bootstrap.sh"; brutal_ensure_base_image "$1"' _ "$task_root"
    else
        brutal_ensure_base_image "$task_root"
    fi
    if [[ ${BRUTAL_WSL_NATIVE:-} != 1 ]]; then
        printf '%s\n' 'Linux receiver dependencies are ready.'
    fi
    exit 0
fi

if "$task_use_sudo"; then
    [[ -z ${BRUTAL_RR_APP_KEY:-} ]] || printf '%s\n' 'Note: a RadioReference key in an environment variable is not forwarded through sudo; use the private .setup-cache key file instead.'
    task_image=${BRUTAL_OP25_IMAGE:-$BRUTAL_LOCAL_IMAGE}
    exec sudo -- env "BRUTAL_OP25_IMAGE=$task_image" bash "$task_root/brutal-op25.sh"
fi
exec bash "$task_root/brutal-op25.sh"
