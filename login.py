import time
import os
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# ====================== KONFIGURASI TELEGRAM ======================
TELEGRAM_BOT_TOKEN = "8333206393:AAG8Z76SSbgAEAC1a3oPT8XhAF9t_rDOq3A"          # contoh: 7123456789:AAH...
TELEGRAM_CHAT_ID   = "-1003532458425"            # contoh: 123456789

def log(msg, level="INFO"):
    """Print log profesional dengan timestamp"""
    now = datetime.now().strftime("%H:%M:%S")
    colors = {
        "INFO": "\033[94m",      # biru
        "SUCCESS": "\033[92m",   # hijau
        "WARNING": "\033[93m",   # kuning
        "ERROR": "\033[91m",     # merah
        "RESET": "\033[0m"
    }
    color = colors.get(level, colors["INFO"])
    print(f"{now} {color}[{level}]{colors['RESET']} {msg}")

def send_telegram(message: str, photo_path: str = None):
    """Kirim pesan + optional screenshot ke Telegram"""
    try:
        if photo_path and os.path.exists(photo_path):
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            with open(photo_path, "rb") as photo:
                files = {"photo": photo}
                data = {"chat_id": TELEGRAM_CHAT_ID, "caption": message}
                requests.post(url, data=data, files=files, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
            requests.post(url, data=data, timeout=15)
    except Exception as e:
        log(f"Gagal kirim Telegram: {e}", "ERROR")

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

# ====================== BACA AKUN ======================
with open("akun.txt", "r") as file:
    credentials = file.read().splitlines()

log(f"Total akun yang akan diproses: {len(credentials)}", "INFO")
send_telegram(f"🚀 Mulai proses login {len(credentials)} akun CodeSignal")

success_count = 0
fail_count = 0

for index, credential in enumerate(credentials):
    try:
        email, password = credential.split('|')
    except:
        log(f"Format akun salah di baris {index+1}", "ERROR")
        continue

    log(f"Memproses akun [{index+1}/{len(credentials)}]: {email}", "INFO")
    send_telegram(f"🔐 Login dimulai → {email}")

    chrome_options = Options()
    chrome_options.add_argument("window-size=400,700")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])

    profile_dir = f"chrome_profile_{index}"
    if not os.path.exists(profile_dir):
        os.makedirs(profile_dir)
    chrome_options.add_argument(f"user-data-dir={os.path.abspath(profile_dir)}")

    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        # Jika pakai webdriver-manager:
        # from webdriver_manager.chrome import ChromeDriverManager
        # driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

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
        time.sleep(18)  # tunggu proses login

        # Screenshot setelah login
        ss = take_screenshot(driver, email, "after_login")
        send_telegram(f"✅ Login berhasil → {email}", ss)
        log(f"Berhasil login: {email}", "SUCCESS")
        success_count += 1

        # Coba klik Skip (jika muncul)
        try:
            submit_button = driver.find_element(By.XPATH, '/html/body/div/div/footer/button[1]/span')
            submit_button.click()
            time.sleep(6)
            ss_skip = take_screenshot(driver, email, "after_skip")
            send_telegram(f"➡️ Skip berhasil → {email}", ss_skip)
            log(f"Skip berhasil untuk {email}", "SUCCESS")
        except:
            log(f"Tombol Skip tidak ditemukan (mungkin sudah melewati)", "WARNING")

    except Exception as e:
        fail_count += 1
        error_msg = f"❌ Gagal login {email}\nError: {str(e)}"
        log(error_msg, "ERROR")
        ss = None
        if driver:
            ss = take_screenshot(driver, email, "error")
        send_telegram(error_msg, ss)

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
        log(f"Browser ditutup untuk {email}", "INFO")
        time.sleep(1)

# Ringkasan akhir
summary = f"""
🏁 Proses Login Selesai
✅ Berhasil : {success_count}
❌ Gagal    : {fail_count}
📊 Total    : {len(credentials)}
"""
log(summary.strip(), "SUCCESS")
send_telegram(summary)

print("\n" + "="*50)
log("Semua akun selesai diproses. Siap menjalankan run.py", "SUCCESS")