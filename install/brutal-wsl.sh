#!/usr/bin/env bash
# Guided Windows launch with Docker Engine in a real Ubuntu WSL distribution.
# Windows connects RTL USB or streams a selected SDRplay radio; OP25 and Docker stay in Linux.
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
                'Uses Ubuntu WSL and a local Linux Docker Engine. Windows connects the selected radio.'
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
task_rsp_script=$(wslpath -w "$task_root/install/wsl-rsp-tcp.ps1")
task_bus=''
task_attached=0
task_rsp_pid=''
task_rsp_helper_pid=''
task_rsp_result_file=''
task_cleanup() {
    if [[ -n $task_rsp_pid ]]; then
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$task_rsp_script" -Mode stop -ServerProcessId "$task_rsp_pid" || true
    fi
    if [[ $task_attached == 1 && -n $task_bus ]]; then
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$task_usb_script" -Mode detach -BusId "$task_bus" || true
    fi
    if [[ -n $task_rsp_result_file ]]; then rm -f -- "$task_rsp_result_file"; fi
}
trap task_cleanup EXIT

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
    --volume brutal-op25-data:/data --entrypoint python "${BRUTAL_OP25_IMAGE:-$BRUTAL_LOCAL_IMAGE}" \
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

if [[ $task_preset == rspdxr2 ]]; then
    task_host_ip=$(ip -4 route show default | awk '/^default / {print $3; exit}')
    [[ $task_host_ip =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
        printf '%s\n' 'Could not locate the Windows side of the WSL network for SDRplay streaming.' >&2; exit 1;
    }
    task_license_args=()
    if ! powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$task_rsp_script" -Mode check-api; then
        . "$task_root/install/sdrplay-license.sh"
        brutal_request_sdrplay_license "$task_root/docs/SDRplay-EULA.txt" windows || exit 1
        task_license_args=(-LicenseAccepted)
    fi
    task_rsp_result_file=$(mktemp /tmp/brutal-op25-rsp-handoff.XXXXXXXX)
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$task_rsp_script" \
        -Mode start -Address "$task_host_ip" "${task_license_args[@]}" >"$task_rsp_result_file" 2>&1 &
    task_rsp_helper_pid=$!
    for ((task_attempt=0; task_attempt<80; task_attempt++)); do
        if grep -q '^BRUTAL_RSP_TCP=' "$task_rsp_result_file"; then break; fi
        if ! kill -0 "$task_rsp_helper_pid" 2>/dev/null; then break; fi
        sleep 0.25
    done
    task_rsp_result=$(<"$task_rsp_result_file")
    if [[ $task_rsp_result != *BRUTAL_RSP_TCP=* ]]; then
        printf '%s\n' "$task_rsp_result" | tr -d '\r' >&2
        printf '%s\n' 'Windows SDRplay stream setup failed. Your saved systems remain available.' >&2; exit 1
    fi
    printf '%s\n' "$task_rsp_result" | sed '/^BRUTAL_RSP_TCP=/d' | tr -d '\r'
    task_rsp_marker=$(printf '%s\n' "$task_rsp_result" | tr -d '\r' | grep '^BRUTAL_RSP_TCP=' | tail -n 1) || {
        printf '%s\n' 'The Windows SDRplay server did not return its local stream address.' >&2; exit 1;
    }
    IFS='|' read -r task_rsp_address task_rsp_pid <<< "${task_rsp_marker#BRUTAL_RSP_TCP=}"
    [[ $task_rsp_address == "$task_host_ip:1234" && $task_rsp_pid =~ ^[1-9][0-9]*$ ]] || {
        printf '%s\n' 'The Windows SDRplay server returned invalid connection details.' >&2; exit 1;
    }
    if ! python3 - "$task_host_ip" <<'PY'
import socket, sys
try:
    with socket.create_connection((sys.argv[1], 1234), timeout=4) as stream:
        stream.settimeout(4)
        header = b''
        while len(header) < 12:
            part = stream.recv(12 - len(header))
            if not part:
                break
            header += part
        if len(header) != 12 or header[:4] != b'RTL0':
            raise OSError('invalid SDRplay stream header')
except OSError as exc:
    print('Linux cannot reach the selected Windows SDRplay stream: ' + str(exc), file=sys.stderr)
    sys.exit(1)
PY
    then
        printf '%s\n' 'Check the Windows firewall for the local WSL connection, then try again. Your saved systems are unchanged.' >&2
        exit 1
    fi
    export BRUTAL_RSP_TCP_ADDR=$task_rsp_address BRUTAL_SELECTED_PROFILE=$task_preset BRUTAL_RESUME_LISTEN=$task_resume
    exec_status=0
    BRUTAL_WSL_HANDOFF=1 BRUTAL_HANDOFF_NONCE=$task_nonce \
        bash "$task_root/brutal-op25.sh" --no-usb || exec_status=$?
    exit "$exec_status"
fi

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

export BRUTAL_SELECTED_PROFILE=$task_preset BRUTAL_RESUME_LISTEN=$task_resume
exec_status=0
BRUTAL_WSL_HANDOFF=1 BRUTAL_HANDOFF_NONCE=$task_nonce \
    bash "$task_root/brutal-op25.sh" --device "$task_device" || exec_status=$?
exit "$exec_status"
