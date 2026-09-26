import time
import os
import requests
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# ====================== SETTING ======================
NUM_PARALLEL = 5              # Berapa clone Chrome dibuka bersamaan
DELAY_ANTAR_CLONE = 3         # Delay (detik) setiap kali buka clone baru
WAIT_AFTER_LOGIN = 18         # Tunggu setelah submit form login (detik)
WAIT_AFTER_SKIP = 6           # Tunggu setelah klik Skip (detik)

# ====================== KONFIGURASI TELEGRAM ======================
TELEGRAM_BOT_TOKEN = "8333206393:AAG8Z76SSbgAEAC1a3oPT8XhAF9t_rDOq3A"
TELEGRAM_CHAT_ID   = "-1003532458425"

# Rate limit Telegram (hindari 429)
_telegram_lock = threading.Lock()
_last_telegram_send = 0.0
TELEGRAM_MIN_INTERVAL = 1.2


def log(msg, level="INFO"):
    """Print log profesional dengan timestamp"""
    now = datetime.now().strftime("%H:%M:%S")
    colors = {
        "INFO": "\033[94m",
        "SUCCESS": "\033[92m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
        "RESET": "\033[0m"
    }
    color = colors.get(level, colors["INFO"])
    print(f"{now} {color}[{level}]{colors['RESET']} {msg}", flush=True)


def send_telegram(message: str, photo_path: str = None):
    """Kirim pesan + optional screenshot ke Telegram (dengan rate-limit + retry 429)"""
    global _last_telegram_send

    max_retries = 4
    for attempt in range(1, max_retries + 1):
        with _telegram_lock:
            now = time.time()
            wait = TELEGRAM_MIN_INTERVAL - (now - _last_telegram_send)
            if wait > 0:
                time.sleep(wait)
            _last_telegram_send = time.time()

        try:
            if photo_path and os.path.exists(photo_path):
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                with open(photo_path, "rb") as photo:
                    files = {"photo": photo}
                    data = {"chat_id": TELEGRAM_CHAT_ID, "caption": str(message)[:1000]}
                    r = requests.post(url, data=data, files=files, timeout=30)
            else:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                data = {"chat_id": TELEGRAM_CHAT_ID, "text": str(message)[:4000]}
                r = requests.post(url, data=data, timeout=15)

            if r.status_code == 200:
                return True

            if r.status_code == 429:
                try:
                    body = r.json()
                    retry_after = int(body.get("parameters", {}).get("retry_after", 5))
                except Exception:
                    retry_after = 5 + attempt * 2
                log(f"Telegram 429 → tunggu {retry_after}s (retry {attempt}/{max_retries})", "WARNING")
                time.sleep(retry_after)
                continue

            log(f"Telegram HTTP {r.status_code}: {r.text[:200]}", "ERROR")
            return False

        except Exception as e:
            log(f"Gagal kirim Telegram: {e}", "ERROR")
            if attempt < max_retries:
                time.sleep(2 * attempt)
                continue
            return False
    return False


def take_screenshot(driver, email, label):
    """Ambil screenshot dan simpan"""
    os.makedirs("screenshots_login", exist_ok=True)
    safe_email = email.replace("@", "_").replace(".", "_")
    filename = f"screenshots_login/{safe_email}_{label}_{int(time.time())}.png"
    try:
        driver.save_screenshot(filename)
        return filename
    except Exception as e:
        log(f"Gagal ambil screenshot: {e}", "WARNING")
        return None


def clear_profile_locks(profile_dir):
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort"):
        path = os.path.join(profile_dir, name)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def login_one_account(index, email, password, delay_before_open=0):
    """Login satu akun. Return True jika sukses, False jika gagal."""
    if delay_before_open > 0:
        log(f"Delay {delay_before_open}s sebelum buka clone → {email}", "INFO")
        time.sleep(delay_before_open)

    log(f"Memproses akun [{index+1}]: {email}", "INFO")
    send_telegram(f"🔐 Login dimulai → {email}")

    chrome_options = Options()
    chrome_options.binary_location = os.environ.get("CHROME_BINARY", "/usr/bin/google-chrome")
    chrome_options.add_argument("window-size=400,700")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--remote-debugging-port=0")
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])

    profile_dir = f"chrome_profile_{index}"
    os.makedirs(profile_dir, exist_ok=True)
    clear_profile_locks(profile_dir)
    chrome_options.add_argument(f"user-data-dir={os.path.abspath(profile_dir)}")

    driver = None
    try:
        service = Service(executable_path=os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver"))
        last_err = None
        for attempt in range(1, 4):
            clear_profile_locks(profile_dir)
            try:
                driver = webdriver.Chrome(service=service, options=chrome_options)
                last_err = None
                break
            except Exception as e:
                last_err = e
                log(f"Chrome gagal attempt {attempt}/3 untuk {email}: {e}", "WARNING")
                time.sleep(2 * attempt)
        if last_err is not None:
            raise last_err

        driver.get("https://identity.codesignal.com/auth/login")
        driver.implicitly_wait(12)

        # Input email & password
        email_field = driver.find_element(By.XPATH, '/html/body/div/div[2]/div/div[2]/div/div[1]/form/div[1]/div/input')
        password_field = driver.find_element(By.XPATH, '/html/body/div/div[2]/div/div[2]/div/div[1]/form/div[2]/div[1]/div/input')

        email_field.clear()
        email_field.send_keys(email)
        password_field.clear()
        password_field.send_keys(password)
        password_field.send_keys(Keys.RETURN)

        log(f"Form login dikirim untuk {email}", "INFO")
        time.sleep(WAIT_AFTER_LOGIN)

        # Screenshot setelah login
        ss = take_screenshot(driver, email, "after_login")
        send_telegram(f"✅ Login berhasil → {email}", ss)
        log(f"Berhasil login: {email}", "SUCCESS")

        # Coba klik Skip (jika muncul)
        try:
            submit_button = driver.find_element(By.XPATH, '/html/body/div/div/footer/button[1]/span')
            submit_button.click()
            time.sleep(WAIT_AFTER_SKIP)
            ss_skip = take_screenshot(driver, email, "after_skip")
            send_telegram(f"➡️ Skip berhasil → {email}", ss_skip)
            log(f"Skip berhasil untuk {email}", "SUCCESS")
        except Exception:
            log(f"Tombol Skip tidak ditemukan (mungkin sudah melewati) → {email}", "WARNING")

        return True

    except Exception as e:
        error_msg = f"❌ Gagal login {email}\nError: {str(e)}"
        log(error_msg, "ERROR")
        ss = None
        if driver:
            try:
                ss = take_screenshot(driver, email, "error")
            except Exception:
                pass
        send_telegram(error_msg, ss)
        return False

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        clear_profile_locks(profile_dir)
        log(f"Browser ditutup untuk {email}", "INFO")


def main():
    if not os.path.exists("akun.txt"):
        log("File akun.txt tidak ditemukan!", "ERROR")
        return

    with open("akun.txt", "r") as file:
        lines = [ln.strip() for ln in file.read().splitlines() if ln.strip() and "|" in ln]

    if not lines:
        log("akun.txt kosong atau format salah", "ERROR")
        return

    accounts = []
    for idx, line in enumerate(lines):
        try:
            email, password = line.split("|", 1)
            email, password = email.strip(), password.strip()
            accounts.append((idx, email, password))
        except Exception:
            log(f"Format akun salah di baris {idx+1}", "ERROR")

    total = len(accounts)
    log(f"Total akun yang akan diproses: {total} | Parallel = {NUM_PARALLEL}", "INFO")
    send_telegram(f"🚀 Mulai proses login {total} akun CodeSignal (parallel={NUM_PARALLEL})")

    success_count = 0
    fail_count = 0

    # Proses batch per NUM_PARALLEL
    for i in range(0, total, NUM_PARALLEL):
        batch = accounts[i:i + NUM_PARALLEL]
        batch_num = i // NUM_PARALLEL + 1
        log(f"=== Batch {batch_num}: membuka {len(batch)} clone ===", "INFO")
        send_telegram(f"🔄 Batch {batch_num} → {len(batch)} Chrome dibuka bersamaan")

        with ThreadPoolExecutor(max_workers=NUM_PARALLEL) as executor:
            futures = {}
            for j, (idx, email, password) in enumerate(batch):
                # Delay bertahap: clone ke-0 = 0s, ke-1 = 3s, ke-2 = 6s, dst
                delay = j * DELAY_ANTAR_CLONE
                future = executor.submit(login_one_account, idx, email, password, delay)
                futures[future] = email

            for future in as_completed(futures):
                email = futures[future]
                try:
                    ok = future.result()
                    if ok:
                        success_count += 1
                    else:
                        fail_count += 1
                except Exception as e:
                    fail_count += 1
                    log(f"Thread {email} exception: {e}", "ERROR")

        time.sleep(1)  # jeda singkat antar batch

    # Ringkasan akhir
    summary = f"""
🏁 Proses Login Selesai
✅ Berhasil : {success_count}
❌ Gagal    : {fail_count}
📊 Total    : {total}
"""
    log(summary.strip(), "SUCCESS")
    send_telegram(summary)

    print("\n" + "=" * 50)
    log("Semua akun selesai diproses. Siap menjalankan run.py", "SUCCESS")


if __name__ == "__main__":
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":99"
    main()
