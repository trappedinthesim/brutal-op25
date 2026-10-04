#!/usr/bin/env bash
# Public-source bootstrap: no Git client or GitHub account is required after release.
set -euo pipefail
task_update=0
task_no_launch=0
task_archive=''
task_install=${BRUTAL_INSTALL_PATH:-"$HOME/brutal-op25"}
while (($#)); do
    case "$1" in
        --update) task_update=1 ;;
        --no-launch) task_no_launch=1 ;;
        --archive) shift; task_archive=${1:?Supply an archive path} ;;
        --install-path) shift; task_install=${1:?Supply an installation path} ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done
[[ $task_install == /* && $task_install != / ]] || {
    printf '%s\n' 'Use an absolute installation path below your home or another writable directory.' >&2; exit 2;
}
task_parent=$(dirname -- "$task_install")
task_name=$(basename -- "$task_install")
mkdir -p -- "$task_parent"
task_parent=$(cd -- "$task_parent" && pwd -P)
task_install="$task_parent/$task_name"
if [[ -e $task_install && $task_update == 0 ]]; then
    printf 'Brutal OP25 already exists at %s. Use --update to replace program files.\n' "$task_install" >&2
    exit 1
fi
if [[ ! -d $task_install && $task_update == 1 ]]; then
    printf 'No installation exists at %s. Run without --update first.\n' "$task_install" >&2
    exit 1
fi
task_work=$(mktemp -d)
task_backup=''
task_moved=0
task_cleanup() {
    local task_status=$?
    if ((task_status != 0)) && [[ -n $task_backup ]]; then
        if ((task_moved)) && [[ -d $task_install ]]; then
            local task_failed="$task_parent/$task_name.failed.$(date -u +%Y%m%d%H%M%S)"
            mv -- "$task_install" "$task_failed"
            printf 'Failed update retained at %s\n' "$task_failed" >&2
        fi
        if [[ ! -e $task_install && -d $task_backup ]]; then
            mv -- "$task_backup" "$task_install"
            printf '%s\n' 'Previous program files restored.' >&2
        fi
    fi
    [[ $task_work == /tmp/tmp.* || $task_work == "${TMPDIR:-/tmp}"/tmp.* ]] && rm -r -- "$task_work"
}
trap task_cleanup EXIT
if [[ -n $task_archive ]]; then
    cp -- "$task_archive" "$task_work/source.tar.gz"
else
    printf '%s\n' 'Downloading Brutal OP25 source from GitHub (no Git client or account required).'
    task_url='https://github.com/trappedinthesim/brutal-op25/archive/refs/heads/main.tar.gz'
    if command -v curl >/dev/null; then
        curl --fail --location --silent --show-error "$task_url" --output "$task_work/source.tar.gz"
    elif command -v wget >/dev/null; then
        wget --quiet --output-document="$task_work/source.tar.gz" "$task_url"
    else
        printf '%s\n' 'Install curl or wget to download the public source archive.' >&2
        exit 1
    fi
fi
mkdir -- "$task_work/payload"
tar -xzf "$task_work/source.tar.gz" -C "$task_work/payload" --strip-components=1
for task_file in Launch-Brutal-OP25.cmd install-brutal-op25.sh install/image-bootstrap.sh build/image-release.txt; do
    [[ -f $task_work/payload/$task_file ]] || {
        printf 'Downloaded source archive is missing %s.\n' "$task_file" >&2; exit 1;
    }
done
task_release=$(tr -d '\r\n' < "$task_work/payload/build/image-release.txt")
[[ $task_release =~ ^ghcr\.io/trappedinthesim/brutal-op25:[a-zA-Z0-9._-]+$ ]] || {
    printf '%s\n' 'Downloaded source archive has an invalid release-image reference.' >&2; exit 1;
}
if ((task_update)); then
    task_backup="$task_parent/$task_name.previous.$(date -u +%Y%m%d%H%M%S)"
    [[ ! -e $task_backup ]] || { printf 'Update backup already exists: %s\n' "$task_backup" >&2; exit 1; }
    mv -- "$task_install" "$task_backup"
fi
mv -- "$task_work/payload" "$task_install"
task_moved=1
bash "$task_install/install-brutal-op25.sh" --prepare-only
if ((task_update)); then bash "$task_install/install-brutal-op25.sh" --update-image; fi
printf 'Brutal OP25 ready at %s\n' "$task_install"
if [[ -n $task_backup ]]; then printf 'Previous program files kept at %s\n' "$task_backup"; fi
if ((task_no_launch == 0)); then bash "$task_install/install-brutal-op25.sh"; fi
