#!/usr/bin/env bash
# Linux/WSL host launcher. The separate installer prepares host prerequisites.
set -euo pipefail
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
task_image=${BRUTAL_OP25_IMAGE:-brutal-op25:0.3.0-dev.23}
task_original_args=("$@")
task_device=''
task_no_usb=false
task_build=false
while (($#)); do
    case "$1" in
        --build) task_build=true ;;
        --no-usb) task_no_usb=true ;;
        --device) shift; task_device=${1:?Supply /dev/bus/usb/BBB/DDD} ;;
        --help) printf '%s\n' 'Brutal OP25 - built on boatbod/op25' \
            'Usage: bash brutal-op25.sh [--build] [--no-usb | --device /dev/bus/usb/BBB/DDD]' \
            'Uses separate volume brutal-op25-data. --no-usb allows import/manage; the Windows SDRplay launcher also uses a local stream.'; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done
# Enter the dedicated WSL launcher unless it is invoking this Linux runner.
if [[ ! -f /.dockerenv ]] && grep -qi microsoft /proc/sys/kernel/osrelease &&
   [[ ${BRUTAL_WSL_NATIVE:-} != 1 ]] && ((${#task_original_args[@]} == 0)); then
    exec bash "$task_root/install/brutal-wsl.sh" "${task_original_args[@]}"
fi
command -v docker >/dev/null || { printf 'Docker is missing. Run bash "%s/install-brutal-op25.sh" for guided installation.\n' "$task_root" >&2; exit 1; }
. "$task_root/install/image-bootstrap.sh"
[[ $(docker info --format '{{.OSType}}') == linux ]] || { printf '%s\n' 'A Linux Docker engine is required.' >&2; exit 1; }
# USB nodes belong to this host only; do not pass them to an unrelated remote engine.
task_endpoint=${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}
[[ "$task_endpoint" == unix://* ]] || { printf '%s\n' 'Use a local Linux Docker socket. Remote Docker contexts need their own device configuration.' >&2; exit 1; }
if [[ "$task_image" == "$BRUTAL_LOCAL_IMAGE" ]]; then
    brutal_ensure_base_image "$task_root" "$task_build"
elif "$task_build" || ! docker image inspect "$task_image" >/dev/null 2>&1; then
    printf 'Custom image %s is unavailable. Build or pull it before launching.\n' "$task_image" >&2; exit 1
fi
task_usb_args=()
if ! "$task_no_usb"; then
    if [[ -z "$task_device" ]]; then
        task_nodes=()
        printf '%s\n' 'Select the radio already visible to Linux (0: imports only):'
        for task_entry in /sys/bus/usb/devices/*; do
            [[ -r "$task_entry/idVendor" && -r "$task_entry/idProduct" ]] || continue
            task_id="$(<"$task_entry/idVendor"):$(<"$task_entry/idProduct")"
            case "$task_id" in
                1df7:3060) task_label='SDRplay RSPdx-R2 (private driver addon required)' ;;
                0bda:2832|0bda:2838) task_label='RTL-SDR family (confirm exact model in setup)' ;;
                *) continue ;;
            esac
            printf -v task_node '/dev/bus/usb/%03d/%03d' "$(<"$task_entry/busnum")" "$(<"$task_entry/devnum")"
            [[ -c "$task_node" ]] || continue
            task_nodes+=("$task_node")
            printf '  %d. %s - %s\n' "${#task_nodes[@]}" "$task_label" "$task_node"
        done
        if ((${#task_nodes[@]} == 0)); then
            printf '%s\n' 'No supported USB node found. On native Linux check the connection/permissions; on WSL first forward the radio from Windows.'
            task_no_usb=true
        elif ((${#task_nodes[@]} == 1)); then
            task_device=${task_nodes[0]}
            printf 'Using the only connected supported radio: %s\n' "$task_device"
        else
            read -r -p 'Radio number: ' task_choice
            [[ "$task_choice" =~ ^[0-9]+$ ]] || { printf '%s\n' 'Invalid choice' >&2; exit 2; }
            task_choice=$((10#$task_choice))
            if ((task_choice == 0)); then task_no_usb=true
            elif ((task_choice <= ${#task_nodes[@]})); then task_device=${task_nodes[task_choice-1]}
            else printf '%s\n' 'Invalid choice' >&2; exit 2
            fi
        fi
    fi
    if ! "$task_no_usb"; then
        [[ "$task_device" =~ ^/dev/bus/usb/[0-9]{3}/[0-9]{3}$ && -c "$task_device" ]] || {
            printf '%s\n' 'Select an existing USB character device node, not a directory or arbitrary path.' >&2; exit 2;
        }
        task_selected_id=''
        for task_entry in /sys/bus/usb/devices/*; do
            [[ -r "$task_entry/idVendor" && -r "$task_entry/idProduct" ]] || continue
            printf -v task_node '/dev/bus/usb/%03d/%03d' "$(<"$task_entry/busnum")" "$(<"$task_entry/devnum")"
            if [[ "$task_node" == "$task_device" ]]; then
                task_selected_id="$(<"$task_entry/idVendor"):$(<"$task_entry/idProduct")"
                break
            fi
        done
        case "$task_selected_id" in
            1df7:3060)
                if [[ "$task_image" == "$BRUTAL_LOCAL_IMAGE" ]]; then
                    task_addon=brutal-op25-sdrplay:0.3.0-dev.23-local
                    if "$task_build" || ! brutal_sdrplay_addon_current "$task_addon" || \
                        ! docker run --rm --network none --read-only --cap-drop ALL \
                            --tmpfs /tmp --tmpfs /home/op25:uid=1000,gid=1000 \
                            --entrypoint python "$task_addon" -c \
                            'from hardware_check import check_profile; r=check_profile("rspdxr2"); assert r["software_dependencies_present"], r["missing"]'; then
                        printf '%s\n' 'Preparing the RSPdx-R2 driver addon for this computer.'
                        bash "$task_root/install/prepare-sdrplay.sh"
                    fi
                    task_image=$task_addon
                fi ;;
            0bda:2832|0bda:2838) ;;
            *) printf '%s\n' 'Selected USB node is not a supported RTL-SDR or RSPdx-R2. Nothing started.' >&2; exit 2 ;;
        esac
        task_mode=$(stat -c '%a' -- "$task_device")
        task_group_access=$(( (8#$task_mode >> 3) & 6 ))
        task_other_access=$(( 8#$task_mode & 6 ))
        if ((task_group_access != 6 && task_other_access != 6)); then
            printf '%s\n' 'Making only the selected radio USB node group-readable/writable until this USB node is recreated.'
            if ((EUID == 0)); then chmod g+rw -- "$task_device"
            elif command -v sudo >/dev/null; then sudo chmod g+rw -- "$task_device"
            else printf '%s\n' 'USB permission repair needs sudo. Install sudo or grant the selected device group read/write access.' >&2; exit 1
            fi
        fi
        task_group=$(stat -c '%g' -- "$task_device")
        task_usb_args=(--device "$task_device:$task_device:rw" --group-add "$task_group")
    fi
fi
# Fail clearly before docker does: a bind error from docker run never says what holds the port.
for task_port in 8080 9000; do
    if (exec 3<>"/dev/tcp/127.0.0.1/$task_port") 2>/dev/null; then
        task_holder=$(docker ps --filter "publish=$task_port" --format '{{.Names}} ({{.Image}})' 2>/dev/null | paste -sd, -)
        if [[ -n "$task_holder" ]]; then task_detail="Docker container $task_holder is using it"
        else task_detail='another program is using it'; fi
        printf 'Port %s on this computer is already in use: %s. Close that receiver or program, then launch again. Nothing was started.\n' \
            "$task_port" "$task_detail" >&2
        exit 1
    fi
done
task_secret_args=()
task_mode_args=()
if [[ ${TERM:-} =~ ^[a-zA-Z0-9._+-]{1,64}$ ]]; then task_mode_args+=(--env "TERM=$TERM"); fi
if [[ ${NO_COLOR+x} ]]; then task_mode_args+=(--env NO_COLOR=1); fi
if "$task_no_usb" && [[ ${BRUTAL_WSL_HANDOFF:-} != 1 ]]; then task_mode_args+=(--env BRUTAL_SETUP_ONLY=1); fi
if [[ ${BRUTAL_WSL_HANDOFF:-} == 1 ]]; then
    [[ ${BRUTAL_HANDOFF_NONCE:-} =~ ^[a-f0-9]{32}$ ]] || { printf '%s\n' 'Invalid WSL handoff nonce.' >&2; exit 2; }
    task_mode_args+=(--env BRUTAL_WINDOWS_LAUNCHER=1 --env "BRUTAL_HANDOFF_NONCE=$BRUTAL_HANDOFF_NONCE")
fi
if [[ -n ${BRUTAL_SELECTED_PROFILE:-} ]]; then
    [[ $BRUTAL_SELECTED_PROFILE == rtl || $BRUTAL_SELECTED_PROFILE == rtlv4 || $BRUTAL_SELECTED_PROFILE == rspdxr2 ]] || {
        printf '%s\n' 'Invalid selected SDR profile.' >&2; exit 2;
    }
    task_mode_args+=(--env "BRUTAL_SELECTED_PROFILE=$BRUTAL_SELECTED_PROFILE")
fi
if [[ -n ${BRUTAL_RSP_TCP_ADDR:-} ]]; then
    [[ ${BRUTAL_WINDOWS_LAUNCHER:-${BRUTAL_WSL_HANDOFF:-}} == 1 && $BRUTAL_RSP_TCP_ADDR =~ ^[0-9.]+:[0-9]{4,5}$ ]] || {
        printf '%s\n' 'Invalid Windows SDRplay stream address.' >&2; exit 2;
    }
    task_mode_args+=(--env "BRUTAL_RSP_TCP_ADDR=$BRUTAL_RSP_TCP_ADDR")
fi
if [[ -n ${BRUTAL_RESUME_LISTEN:-} ]]; then
    [[ $BRUTAL_RESUME_LISTEN =~ ^[a-f0-9]{32}$ ]] || { printf '%s\n' 'Invalid saved-system continuation.' >&2; exit 2; }
    task_mode_args+=(--env "BRUTAL_RESUME_LISTEN=$BRUTAL_RESUME_LISTEN")
fi
task_key_file=${BRUTAL_RR_KEY_FILE:-$task_root/.setup-cache/radioreference_app_key}
if [[ -f "$task_key_file" ]]; then
    [[ "$task_key_file" != *,* ]] || { printf '%s\n' 'The application-key file path cannot contain a comma.' >&2; exit 2; }
    task_secret_args=(--mount "type=bind,source=$task_key_file,target=/run/secrets/radioreference_app_key,readonly")
fi
exec docker run --rm -it --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --tmpfs /tmp:size=128m,mode=1777 \
    --tmpfs /home/op25:size=16m,uid=1000,gid=1000,mode=0700 \
    --volume brutal-op25-data:/data --env BRUTAL_RR_APP_KEY "${task_secret_args[@]}" "${task_usb_args[@]}" "${task_mode_args[@]}" \
    --publish 127.0.0.1:8080:8080 --publish 127.0.0.1:9000:9000 \
    "$task_image" python brutal_cli.py
