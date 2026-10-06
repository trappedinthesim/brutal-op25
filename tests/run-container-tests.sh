#!/usr/bin/env bash
# Mount only test/source inputs. Never mount .setup-cache, credentials or home.
set -euo pipefail
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
task_image=${BRUTAL_OP25_IMAGE:-brutal-op25:0.3.0-dev.24}
task_mounts=()
for task_dir in src tests build install bootstrap docs .github; do
    task_mounts+=(--mount "type=bind,source=$task_root/$task_dir,target=/app/$task_dir,readonly")
done
for task_file in .dockerignore LICENSE THIRD-PARTY-NOTICES.md Launch-Brutal-OP25.cmd brutal-op25.sh install-brutal-op25.sh README.md; do
    task_mounts+=(--mount "type=bind,source=$task_root/$task_file,target=/app/$task_file,readonly")
done
exec docker run --rm --network none --read-only --cap-drop ALL \
    --tmpfs /tmp:exec,size=256m,mode=1777 \
    --tmpfs /home/op25:size=16m,uid=1000,gid=1000 \
    --env PYTHONPATH=/app/src:/app/build --workdir /app \
    "${task_mounts[@]}" --entrypoint python "$task_image" \
    -m unittest discover -s tests -p 'test_*.py'
