#!/usr/bin/env bash
# Run the iScale 3D worker on this GPU computer for a server with CIVIL_3D=remote.
#   ISCALE_SERVER       the server, for example http://192.168.1.135:8765
#   ISCALE_TOKEN_FILE   file with the server's CIVIL_WORKER_TOKEN (chmod 600)
#   ROBOFLOW_KEY_FILE   optional: file with the Roboflow key (LingBot clips check it is set)
#   ISCALE_WORKER_DATA  scratch folder for jobs (deleted after each upload)
set -euo pipefail
cd "$(dirname "$0")/.."
export CIVIL_DATA_DIR="${ISCALE_WORKER_DATA:-$HOME/.local/share/iscale-worker}"
export CIVIL_XMPP=off
if [ -n "${ROBOFLOW_KEY_FILE:-}" ] && [ -r "$ROBOFLOW_KEY_FILE" ]; then
  export ROBOFLOW_API_KEY="$(tr -d '\r\n' < "$ROBOFLOW_KEY_FILE")"
fi
mkdir -p "$CIVIL_DATA_DIR"
# NixOS keeps the NVIDIA driver (libcuda) in /run/opengl-driver/lib, which a login shell finds but a
# systemd service does not; without it PyTorch falls back to the CPU and LingBot-Map fails.
if [ -d /run/opengl-driver/lib ]; then
  export LD_LIBRARY_PATH="/run/opengl-driver/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
# Don't take jobs this computer can only fail: LingBot-Map's Python must see the GPU.
LB_PY="$(.venv/bin/python -c 'import json;print(json.load(open("config/video.json"))["lingbot"]["python"])')"
if ! "$LB_PY" -c 'import sys, torch; sys.exit(0 if torch.cuda.is_available() else 1)' 2>/dev/null; then
  echo "3D worker: LingBot-Map's Python ($LB_PY) cannot see a CUDA GPU; not taking jobs (retrying in 60 s)" >&2
  sleep 60
  exit 1
fi
exec .venv/bin/civil worker --server "${ISCALE_SERVER:?set ISCALE_SERVER}" --token-file "${ISCALE_TOKEN_FILE:?set ISCALE_TOKEN_FILE}" "$@"
