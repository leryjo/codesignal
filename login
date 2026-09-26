#!/usr/bin/env bash
set -e

CONTAINER_NAME="${CONTAINER_NAME:-codesignal}"

echo "[1] Cek container..."
docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME" || {
  echo "Container $CONTAINER_NAME belum running."
  echo "Jalankan dulu: bash run"
  exit 1
}

echo "[2] Jalankan login.py..."

docker exec -it "$CONTAINER_NAME" bash -lc '
cd /codesignal/data
xvfb-run -a --server-args="-screen 0 1280x720x24" python3 -u /codesignal/login.py
'