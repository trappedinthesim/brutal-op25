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
task_program_manifest() {
    (
        cd -- "$1"
        [[ -z $(find . -type l -print -quit) ]] || return 1
        find . -type f ! -path './.brutal-op25-install' ! -path './.brutal-op25-manifest' -print0 |
            LC_ALL=C sort -z | xargs -0 -r sha256sum
    )
}
task_remove_old_program_versions() {
    local task_candidate task_candidate_name task_suffix task_marker task_manifest task_removed=0 task_legacy=0 task_other=0
    while IFS= read -r -d '' task_candidate; do
        [[ $task_candidate != "$task_backup" && ! -L $task_candidate ]] || continue
        task_candidate_name=$(basename -- "$task_candidate")
        [[ $task_candidate_name == "$task_name.previous."* ]] || continue
        task_suffix=${task_candidate_name#"$task_name.previous."}
        [[ $task_suffix =~ ^[0-9]{14}$ ]] || continue
        [[ $(dirname -- "$(realpath -m -- "$task_candidate")") == "$task_parent" ]] || continue
        task_marker="$task_candidate/.brutal-op25-install"
        task_manifest="$task_candidate/.brutal-op25-manifest"
        if [[ ! -f $task_manifest ]]; then
            ((task_legacy+=1))
            continue
        fi
        [[ -f $task_marker && -f $task_candidate/install-brutal-op25.sh &&
           -f $task_candidate/build/image-release.txt && $(< "$task_marker") == "$task_install" ]] || {
            ((task_other+=1))
            continue
        }
        if ! cmp -s -- "$task_manifest" <(task_program_manifest "$task_candidate"); then
            ((task_other+=1))
            continue
        fi
        rm -r -- "$task_candidate" || return 1
        ((task_removed+=1))
    done < <(find "$task_parent" -mindepth 1 -maxdepth 1 -type d -name "$task_name.previous.*" -print0)
    if ((task_removed)); then printf 'Removed %s older Brutal OP25 program version(s).\n' "$task_removed"; fi
    if ((task_legacy)); then
        printf 'Kept %s older backup folder(s) without a cleanup inventory beside %s. This does not mean you changed them.\n' "$task_legacy" "$task_install" >&2
        printf '%s\n' 'The current installation does not use these folders. They were not auto-deleted because their contents cannot be verified.' >&2
    fi
    if ((task_other)); then
        printf 'Kept %s other backup folder(s) that could not be verified beside %s. They may contain files worth keeping.\n' "$task_other" "$task_install" >&2
    fi
}
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
[[ $task_release =~ ^ghcr\.io/trappedinthesim/brutal-op25-receiver:[a-zA-Z0-9._-]+$ ]] || {
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
printf '%s\n' "$task_install" > "$task_install/.brutal-op25-install"
task_program_manifest "$task_install" > "$task_install/.brutal-op25-manifest"
if ((task_update)); then bash "$task_install/install-brutal-op25.sh" --update-image; fi
printf 'Brutal OP25 ready at %s\n' "$task_install"
if [[ -n $task_backup ]]; then printf 'Previous program files kept at %s\n' "$task_backup"; fi
if ((task_update)); then
    task_remove_old_program_versions || printf '%s\n' 'Old program version cleanup was skipped.' >&2
fi
if ((task_no_launch == 0)); then bash "$task_install/install-brutal-op25.sh"; fi
