#!/usr/bin/env bash
# Disposable Docker volumes only; never touches the user's profile volume.
set -euo pipefail
task_source="brutal-op25-test-transfer${RANDOM}${RANDOM}"
task_target="brutal-op25-test-transfer${RANDOM}${RANDOM}"
task_dir=$(mktemp -d)
task_created_source=0
task_created_target=0
task_cleanup() {
    if ((task_created_source)); then docker volume rm "$task_source" >/dev/null || true; fi
    if ((task_created_target)); then docker volume rm "$task_target" >/dev/null || true; fi
    rm -r -- "$task_dir"
}
trap task_cleanup EXIT
docker volume inspect "$task_source" >/dev/null 2>&1 && { printf '%s\n' 'Test volume already exists.' >&2; exit 1; }
docker volume inspect "$task_target" >/dev/null 2>&1 && { printf '%s\n' 'Test volume already exists.' >&2; exit 1; }
docker volume create "$task_source" >/dev/null
task_created_source=1
docker volume create "$task_target" >/dev/null
task_created_target=1
docker run --rm --network none --volume "$task_source:/data" --entrypoint python brutal-op25:0.3.0-dev.9 -c '
from library import ProfileLibrary
p={"id":"a"*32,"revision":1,"name":"Disposable test","settings":{"hardware":{"profile":"rtlv4"},"site_id":1},"system":{"name":"Disposable test","sites":[],"talkgroups":[]}}
ProfileLibrary("/data/saved-profiles").write(p)
'
BRUTAL_PROFILE_VOLUME="$task_source" bash install/profile-data.sh export "$task_dir/systems.zip"
BRUTAL_PROFILE_VOLUME="$task_target" bash install/profile-data.sh restore "$task_dir/systems.zip"
docker run --rm --network none --volume "$task_target:/data:ro" --entrypoint python brutal-op25:0.3.0-dev.9 -c '
from library import ProfileLibrary
p=ProfileLibrary("/data/saved-profiles").list()
assert len(p)==1 and p[0]["name"]=="Disposable test"
'
docker run --rm --network none --volume "$task_target:/data" --entrypoint python brutal-op25:0.3.0-dev.9 -c '
from library import ProfileLibrary
library=ProfileLibrary("/data/saved-profiles")
p=library.list()[0]
p["revision"]=2
library.write(p)
assert library.read(p["id"])["revision"]==2
'
printf '%s\n' 'PASS: saved-system backup and restore through two disposable Docker volumes'
