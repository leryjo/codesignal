#!/bin/bash
set -e

start_xvfb() {
    export DISPLAY="${DISPLAY:-:99}"
    local display_num="${DISPLAY#:}"

    mkdir -p /tmp/.X11-unix
    chmod 1777 /tmp/.X11-unix 2>/dev/null || true

    if pgrep -x Xvfb >/dev/null 2>&1 && [ -S "/tmp/.X11-unix/X${display_num}" ]; then
        echo "[entrypoint] Xvfb sudah aktif di ${DISPLAY}"
        return 0
    fi

    rm -f "/tmp/.X\( {display_num}-lock" "/tmp/.X11-unix/X \){display_num}" 2>/dev/null || true

    echo "[entrypoint] Starting Xvfb on ${DISPLAY} ..."
    Xvfb "${DISPLAY}" -screen 0 1920x1080x24 -ac +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 &
    sleep 1

    if pgrep -x Xvfb >/dev/null 2>&1; then
        echo "[entrypoint] Xvfb OK"
    else
        echo "[entrypoint] WARNING: Xvfb gagal start. Cek /tmp/xvfb.log"
        cat /tmp/xvfb.log 2>/dev/null || true
    fi
}

keep_alive() {
    start_xvfb
    mkdir -p /codesignal/data/chrome_profiles \
             /codesignal/data/screenshots \
             /codesignal/data/screenshots_login
    touch /codesignal/data/akun.txt

    echo "[entrypoint] Container idle. Siap menerima: bash login / bash startloop"
    echo "[entrypoint] DISPLAY=${DISPLAY}"

    trap 'echo "[entrypoint] stopping"; exit 0' TERM INT
    while true; do
        if ! pgrep -x Xvfb >/dev/null 2>&1; then
            echo "[entrypoint] Xvfb mati, start ulang..."
            start_xvfb
        fi
        sleep 30
    done
}

start_xvfb

mkdir -p /codesignal/data/chrome_profiles \
         /codesignal/data/screenshots \
         /codesignal/data/screenshots_login
touch /codesignal/data/akun.txt

cmd="${1:-idle}"
shift || true

case "$cmd" in
    login)
        echo "[entrypoint] Menjalankan login.py ..."
        cd /codesignal/data
        if [ ! -s akun.txt ]; then
            echo "ERROR: /codesignal/data/akun.txt kosong / tidak ada!"
            echo "Isi dengan format: email|password (satu baris per akun)"
            exit 1
        fi
        exec python3 -u /codesignal/login.py
        ;;
    run|loop)
        echo "[entrypoint] Menjalankan run.py (loop) ..."
        cd /codesignal/data
        if [ ! -s akun.txt ]; then
            echo "ERROR: /codesignal/data/akun.txt kosong / tidak ada!"
            exit 1
        fi
        exec python3 -u /codesignal/run.py
        ;;
    idle|wait|keep)
        keep_alive
        ;;
    bash|sh)
        exec /bin/bash "$@"
        ;;
    help|--help|-h)
        cat <<EOF
========================================
  CodeSignal Docker Helper
========================================
Usage:
  bash run                 → build + start container IDLE (tetap hidup)
  bash login               → docker exec login.py
  bash startloop           → docker exec run.py loop
  bash stoploop            → stop loop

  docker run ... codesignal idle    → container tetap hidup
  docker run ... codesignal login   → jalankan login.py langsung
  docker run ... codesignal run     → jalankan run.py langsung
  docker run ... codesignal bash    → masuk shell
========================================
EOF
        exit 0
        ;;
    *)
        echo "Unknown command: $cmd"
        echo "Gunakan: idle | login | run | bash | help"
        exit 1
        ;;
esac
