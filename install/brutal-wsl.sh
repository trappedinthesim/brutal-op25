#!/usr/bin/env bash
# Guided Windows launch with Docker Engine in a real Ubuntu WSL distribution.
# Windows only supplies the one selected USB radio; OP25 and Docker stay in Linux.
set -euo pipefail
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
. "$task_root/install/image-bootstrap.sh"
task_mode=run
while (($#)); do
    case "$1" in
        --check) task_mode=check ;;
        --prepare-only) task_mode=prepare ;;
        --update-image) task_mode=update ;;
        --rollback-image) task_mode=rollback ;;
        --help)
            printf '%s\n' 'Usage: bash install/brutal-wsl.sh [--check | --prepare-only | --update-image | --rollback-image]' \
                'Uses Ubuntu WSL, a local Linux Docker Engine and the Windows USB bridge.'
            exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done
grep -qi microsoft /proc/sys/kernel/osrelease || {
    printf '%s\n' 'This launcher is for WSL. On native Linux run bash install-brutal-op25.sh.' >&2; exit 1;
}
export BRUTAL_WSL_NATIVE=1
# A Docker Desktop WSL integration may add its CLI/context to PATH. Always use
# this distribution's own daemon; never silently switch back to Desktop.
export DOCKER_HOST=unix:///var/run/docker.sock
if [[ $task_mode == check ]]; then
    exec bash "$task_root/install-brutal-op25.sh" --check
fi
if ((EUID != 0)) && ! docker info >/dev/null 2>&1; then
    command -v sudo >/dev/null || { printf '%s\n' 'Docker setup requires sudo in this WSL distribution.' >&2; exit 1; }
    sudo -v
    task_sudo_args=()
    case "$task_mode" in
        prepare) task_sudo_args=(--prepare-only) ;;
        update) task_sudo_args=(--update-image) ;;
        rollback) task_sudo_args=(--rollback-image) ;;
    esac
    exec sudo -- env BRUTAL_WSL_NATIVE=1 \
        "BRUTAL_DOCKER_INSTALL_ACCEPTED=${BRUTAL_DOCKER_INSTALL_ACCEPTED:-}" \
        "BRUTAL_OP25_IMAGE=${BRUTAL_OP25_IMAGE:-}" \
        "BRUTAL_RR_KEY_FILE=${BRUTAL_RR_KEY_FILE:-}" \
        bash "$task_root/install/brutal-wsl.sh" "${task_sudo_args[@]}"
fi
bash "$task_root/install-brutal-op25.sh" --prepare-only
task_socket=$(readlink -f /var/run/docker.sock 2>/dev/null || true)
[[ $task_socket == /run/docker.sock || $task_socket == /var/run/docker.sock ]] || {
    printf 'Expected the Ubuntu-local Docker socket, found %s. Disable Docker Desktop integration for this distro and retry.\n' "$task_socket" >&2
    exit 1
}
if [[ $task_mode == prepare ]]; then exit 0; fi
if [[ $task_mode == update ]]; then
    exec bash "$task_root/install-brutal-op25.sh" --update-image
fi
if [[ $task_mode == rollback ]]; then
    exec bash "$task_root/install-brutal-op25.sh" --rollback-image
fi
command -v powershell.exe >/dev/null && command -v wslpath >/dev/null || {
    printf '%s\n' 'Windows interop is required to connect a USB radio to WSL. No receiver was started.' >&2; exit 1;
}
command -v flock >/dev/null || { printf '%s\n' 'The WSL launcher needs flock (util-linux).' >&2; exit 1; }
exec 9>/tmp/brutal-op25-wsl.lock
flock -n 9 || { printf '%s\n' 'Brutal OP25 is already running in this WSL distribution.' >&2; exit 1; }
task_usb_script=$(wslpath -w "$task_root/install/wsl-usb.ps1")
task_bus=''
task_attached=0
task_cleanup() {
    if [[ $task_attached == 1 && -n $task_bus ]]; then
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$task_usb_script" -Mode detach -BusId "$task_bus" || true
    fi
}
trap task_cleanup EXIT

printf '\n%s\n' 'BRUTAL OP25 // WINDOWS + WSL' \
    'OP25 and Docker Engine run in Ubuntu. Windows only connects the selected USB radio.' \
    'Dashboard link: http://127.0.0.1:8080/'
task_nonce=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
set +e
BRUTAL_WSL_HANDOFF=1 BRUTAL_HANDOFF_NONCE=$task_nonce \
    bash "$task_root/brutal-op25.sh" --no-usb
task_status=$?
set -e
if ((task_status == 0)); then exit 0; fi
if ((task_status != 88)); then
    printf 'Setup exited with status %s. No USB radio was connected.\n' "$task_status" >&2
    exit "$task_status"
fi

# Read and consume the one-time request from the private Docker volume.
task_request=$(docker run --rm --network none --read-only --cap-drop ALL \
    --volume brutal-op25-data:/data --entrypoint python brutal-op25:0.3.0-dev.5 \
    -c 'from pathlib import Path; p=Path("/data/host-handoff.json"); print(p.read_text()); p.unlink()')
task_fields=$(python3 -c '
import json, re, sys
r = json.loads(sys.stdin.read())
nonce = sys.argv[1]
assert r.get("version") == 1 and r.get("action") == "connect_usb" and r.get("nonce") == nonce
preset = r.get("preset")
resume = r.get("resume_listen", "")
assert preset in ("rtl", "rtlv4", "rspdxr2")
assert resume == "" or re.fullmatch(r"[a-f0-9]{32}", resume)
print(preset + "|" + resume)
' "$task_nonce" <<< "$task_request") || {
    printf '%s\n' 'Invalid or stale USB connection request. No host action was taken.' >&2; exit 1;
}
IFS='|' read -r task_preset task_resume <<< "$task_fields"

task_usb_result=$(powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$task_usb_script" -Mode connect -Profile "$task_preset") || {
    printf '%s\n' 'Windows USB connection failed. Your saved systems remain available.' >&2; exit 1;
}
printf '%s\n' "$task_usb_result" | sed '/^BRUTAL_USB=/d' | tr -d '\r'
task_marker=$(printf '%s\n' "$task_usb_result" | tr -d '\r' | grep '^BRUTAL_USB=' | tail -n 1) || {
    printf '%s\n' 'The Windows USB bridge did not return a radio identity.' >&2; exit 1;
}
IFS='|' read -r task_bus task_serial task_attached <<< "${task_marker#BRUTAL_USB=}"
[[ $task_bus =~ ^[0-9]+-[0-9]+(\.[0-9]+)*$ && $task_serial =~ ^[A-Za-z0-9_-]+$ && $task_attached =~ ^[01]$ ]] || {
    printf '%s\n' 'The USB bridge returned an invalid radio identity.' >&2; exit 1;
}

task_device=''
for ((task_attempt=0; task_attempt<40 && ${#task_device}==0; task_attempt++)); do
    for task_entry in /sys/bus/usb/devices/*; do
        [[ -r $task_entry/serial && -r $task_entry/idVendor && -r $task_entry/idProduct ]] || continue
        [[ $(<"$task_entry/serial") == "$task_serial" ]] || continue
        task_id="$(<"$task_entry/idVendor"):$(<"$task_entry/idProduct")"
        case "$task_preset:$task_id" in
            rtl:0bda:2832|rtl:0bda:2838|rtlv4:0bda:2832|rtlv4:0bda:2838|rspdxr2:1df7:3060) ;;
            *) continue ;;
        esac
        printf -v task_node '/dev/bus/usb/%03d/%03d' "$(<"$task_entry/busnum")" "$(<"$task_entry/devnum")"
        [[ -c $task_node ]] || continue
        [[ -z $task_device ]] || { printf '%s\n' 'More than one Linux USB node matched the selected serial. Refusing to guess.' >&2; exit 1; }
        task_device=$task_node
    done
    [[ -n $task_device ]] || sleep 0.25
done
[[ -n $task_device ]] || { printf 'Radio serial %s was not visible in Ubuntu WSL after USB forwarding.\n' "$task_serial" >&2; exit 1; }
printf 'Linux can see the selected radio: %s\n' "$task_device"

if [[ $task_preset == rspdxr2 ]]; then
    task_addon=brutal-op25-sdrplay:0.3.0-dev.5-local
    if ! brutal_sdrplay_addon_current "$task_addon" || \
       ! docker run --rm --network none --read-only --cap-drop ALL --tmpfs /tmp \
           --tmpfs /home/op25:uid=1000,gid=1000 --entrypoint python "$task_addon" \
           -c 'from hardware_check import check_profile; r=check_profile("rspdxr2"); assert r["software_dependencies_present"], r["missing"]'; then
        bash "$task_root/install/prepare-sdrplay.sh"
    fi
    export BRUTAL_OP25_IMAGE=$task_addon
fi
export BRUTAL_SELECTED_PROFILE=$task_preset BRUTAL_RESUME_LISTEN=$task_resume
exec_status=0
bash "$task_root/brutal-op25.sh" --device "$task_device" || exec_status=$?
exit "$exec_status"
