#!/usr/bin/env bash
# Interactive SDRplay license review. Sourcing this file never accepts a license.

brutal_review_sdrplay_license() {
    local task_license=${1:?Supply the full SDRplay license path}
    [[ -f $task_license ]] || { printf '%s\n' 'SDRplay license text is missing; nothing was installed.' >&2; return 1; }
    printf '\n%s\n' 'SDRPLAY DRIVER LICENSE // RSPdx-R2 ONLY'
    printf '%s\n' 'This is SDRplay’s separate license for its hardware API, not the OP25 license.'
    if [[ -t 0 && -t 1 ]] && command -v less >/dev/null; then
        printf '%s\n' 'Arrows/PgDn scroll; press q to leave the viewer. The decision comes next.'
        LESSSECURE=1 less -X -P'SDRplay license - arrows or PgDn scroll - press q to return - then choose Yes or No' -- "$task_license"
    elif [[ -t 0 && -t 1 ]] && command -v more >/dev/null; then
        printf '%s\n' 'Space advances; press q to leave the viewer. The decision comes next.'
        more -d -- "$task_license"
    else
        printf '%s\n' 'The full agreement follows. The decision comes after the text.'
        cat -- "$task_license"
    fi
}

brutal_request_sdrplay_license() {
    local task_license=${1:?Supply the full SDRplay license path}
    local task_target=${2:-addon}
    local task_consent
    brutal_review_sdrplay_license "$task_license" || return 1
    while true; do
        printf '\n%s\n' 'SDRplay permits this API to be used with its hardware under the agreement above.'
        if [[ $task_target == windows ]]; then
            printf '%s\n' 'The official Windows API will be installed only on this computer; the radio will stream to local Linux.'
        else
            printf '%s\n' 'The addon will be built only on this computer and must not be published without permission.'
        fi
        printf '%s' 'Accept SDRplay’s license and install its driver? [y] Yes  [r] Review again  [n] Cancel: '
        if ! IFS= read -r task_consent; then
            printf '\n%s\n' 'No license decision was received. Nothing was installed.' >&2
            return 1
        fi
        case ${task_consent,,} in
            y|yes|accept) printf '%s\n' 'License accepted. Continuing SDRplay setup...'; return 0 ;;
            r|review) brutal_review_sdrplay_license "$task_license" || return 1 ;;
            n|no|cancel|q) printf '%s\n' 'Cancelled. Your saved profile is unchanged; no addon was built.'; return 1 ;;
            *) printf '%s\n' 'Choose y to accept, r to read again, or n to cancel. Enter alone does nothing.' ;;
        esac
    done
}
