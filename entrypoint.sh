#!/bin/bash
set -e

# Start virtual display (diperlukan karena Chrome non-headless)
if [ -z "$DISPLAY" ] || [ "$DISPLAY" = ":99" ]; then
    echo "[entrypoint] Starting Xvfb on :99 ..."
    Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
    export DISPLAY=:99
    sleep 1
fi

# Pastikan folder data ada
mkdir -p /codesignal/data/chrome_profiles \
         /codesignal/data/screenshots \
         /codesignal/data/screenshots_login

# Symlink agar script (yang menulis ke relative path) tetap bekerja
# Script menulis ke ./chrome_profile_* dan ./screenshots*
# Kita arahkan ke volume agar data persist
if [ ! -L /codesignal/chrome_profiles_link ]; then
    # Script membuat chrome_profile_{index} di current dir
    # Kita biarkan saja, user bisa mount volume ke /codesignal/data
    true
fi

case "$1" in
    login)
        echo "[entrypoint] Menjalankan login.py ..."
        # Pindah ke data dir agar akun.txt & profile ter-mount
        cd /codesignal/data
        # Pastikan akun.txt ada
        if [ ! -f akun.txt ]; then
            echo "ERROR: /codesignal/data/akun.txt tidak ditemukan!"
            echo "Buat file akun.txt dengan format: email|password (satu baris per akun)"
            exit 1
        fi
        # Jalankan dari /codesignal agar import path benar, tapi cwd = data
        exec python /codesignal/login.py
        ;;
    run|loop)
        echo "[entrypoint] Menjalankan run.py (loop) ..."
        cd /codesignal/data
        if [ ! -f akun.txt ]; then
            echo "ERROR: /codesignal/data/akun.txt tidak ditemukan!"
            exit 1
        fi
        exec python /codesignal/run.py
        ;;
    bash|sh)
        exec /bin/bash
        ;;
    help|--help|-h|"")
        cat <<EOF
========================================
  CodeSignal Docker Helper
========================================
Usage:
  docker run ... codesignal login     → jalankan login.py
  docker run ... codesignal run       → jalankan run.py (loop)
  docker run ... codesignal bash      → masuk shell

Data volume (disarankan):
  -v \$(pwd)/data:/codesignal/data

Isi data/akun.txt dengan format:
  email1@example.com|password1
  email2@example.com|password2

Contoh lengkap:
  mkdir -p data
  # isi data/akun.txt
  docker build -t codesignal .
  docker run --rm -it \\
    -v \$(pwd)/data:/codesignal/data \\
    --shm-size=2g \\
    codesignal login
========================================
EOF
        ;;
    *)
        echo "Unknown command: $1"
        echo "Gunakan: login | run | bash | help"
        exit 1
        ;;
esac
