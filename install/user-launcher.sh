#!/usr/bin/env bash
# Sourced by the native-Linux installer. Do not change the user's shell startup files.
brutal_install_user_command() {
    local task_root=$1
    if ((EUID == 0)); then
        printf '%s\n' 'Run setup as your normal user to add a personal brutal-op25 command.'
        return 0
    fi
    if [[ -z ${HOME:-} ]]; then
        printf '%s\n' 'HOME is unavailable; no personal launch command was created.' >&2
        return 0
    fi
    local task_bin="$HOME/.local/bin"
    local task_launcher="$task_bin/brutal-op25"
    local task_marker='# Managed by Brutal OP25 setup'
    if [[ -L "$task_launcher" ]] || {
        [[ -e "$task_launcher" ]] && ! grep -Fxq "$task_marker" "$task_launcher" 2>/dev/null;
    }; then
        printf 'Existing command left unchanged: %s\n' "$task_launcher" >&2
        return 0
    fi
    if ! mkdir -p -- "$task_bin"; then
        printf 'Could not create personal command directory: %s\n' "$task_bin" >&2
        return 0
    fi
    local task_temp
    task_temp=$(mktemp "$task_bin/.brutal-op25.XXXXXXXX") || {
        printf 'Could not create a temporary launch command in %s\n' "$task_bin" >&2
        return 0
    }
    if ! printf '#!/usr/bin/env bash\n%s\nexec bash %q "$@"\n' \
        "$task_marker" "$task_root/install-brutal-op25.sh" > "$task_temp" ||
        ! chmod 0755 "$task_temp" ||
        ! mv -f -- "$task_temp" "$task_launcher"; then
        rm -f -- "$task_temp"
        printf 'Could not add personal launch command: %s\n' "$task_launcher" >&2
        return 0
    fi
    printf 'Next time, launch with: %s\n' "$task_launcher"
    if [[ :$PATH: == *":$task_bin:"* ]]; then
        printf '%s\n' 'You can also type: brutal-op25'
    else
        printf '%s\n' 'After your next login, you may also be able to type: brutal-op25'
    fi
}
