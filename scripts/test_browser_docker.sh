#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker_desktop_bin=/Applications/Docker.app/Contents/Resources/bin

docker_command="$(command -v docker || true)"
if [[ -z "${docker_command}" && -x "${docker_desktop_bin}/docker" ]]; then
  export PATH="${docker_desktop_bin}:${PATH}"
  docker_command="${docker_desktop_bin}/docker"
fi

if [[ -z "${docker_command}" ]]; then
  echo "Docker Desktop is required for browser regression tests." >&2
  exit 1
fi

"${docker_command}" run --rm --init --ipc=host \
  --env HOST_UID="$(id -u)" \
  --env HOST_GID="$(id -g)" \
  --volume "${repo_root}:/work" \
  --workdir /work \
  mcr.microsoft.com/playwright/python:v1.55.0-noble \
  bash -lc '
    apt-get update
    apt-get install --yes ffmpeg
    groupadd --gid "$HOST_GID" browser-tests 2>/dev/null || true
    useradd --uid "$HOST_UID" --gid "$HOST_GID" --create-home browser-tests 2>/dev/null || true
    su browser-tests -s /bin/bash -c "
      export PYTHONUSERBASE=/tmp/browser-tests-python
      export HOME=/tmp/browser-tests-home
      python -m pip install --user --requirement requirements-test.txt
      python scripts/build_site.py
      SITE_ROOT=_site python tests/test_browser.py \"\$@\"
    " bash "$@"
  ' bash "$@"
