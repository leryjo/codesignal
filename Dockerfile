FROM python:3.14-slim-trixie

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CODE_DIR=/codesignal \
    DATA_DIR=/codesignal/data \
    PROFILES_ROOT=/codesignal/data/chrome_profiles \
    CHROME_BINARY=/usr/bin/google-chrome \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    DISPLAY=:99

WORKDIR /codesignal

# System dependencies + Chrome libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl unzip gnupg2 \
    xvfb xauth \
    procps psmisc ca-certificates \
    fonts-liberation \
    libnss3 libxss1 libasound2 libgbm1 libu2f-udev libvulkan1 \
    libgtk-3-0 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
    libxrandr2 libxdamage1 libxcomposite1 libxfixes3 libxi6 \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome
RUN set -eux; \
    mkdir -p /etc/apt/keyrings; \
    curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/keyrings/google.gpg; \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends google-chrome-stable; \
    rm -rf /var/lib/apt/lists/*

# Disable Chrome sync / password manager (lebih stabil di automation)
RUN set -eux; \
    mkdir -p /etc/opt/chrome/policies/managed; \
    printf '%s\n' \
    '{' \
    '  "SyncDisabled": true,' \
    '  "BrowserSignin": 0,' \
    '  "SigninAllowed": false,' \
    '  "PasswordManagerEnabled": false,' \
    '  "CredentialsEnableService": false' \
    '}' > /etc/opt/chrome/policies/managed/policy.json

# Install matching ChromeDriver
RUN set -eux; \
    CHROME_TRIPLE="$(google-chrome --version | awk '{print $3}' | cut -d '.' -f1-3)"; \
    DRIVER_VERSION="$(curl -fsSL "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_${CHROME_TRIPLE}")"; \
    curl -fsSL -o /tmp/chromedriver.zip "https://storage.googleapis.com/chrome-for-testing-public/${DRIVER_VERSION}/linux64/chromedriver-linux64.zip"; \
    unzip /tmp/chromedriver.zip -d /tmp/; \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver; \
    rm -rf /tmp/chromedriver.zip /tmp/chromedriver-linux64; \
    chmod +x /usr/local/bin/chromedriver; \
    ln -sf /usr/local/bin/chromedriver /usr/bin/chromedriver

# Python packages yang dibutuhkan kedua script
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir psutil requests selenium==4.48.0 Pillow pyvirtualdisplay mss pyautogui colorama

# Copy script
COPY login.py run.py entrypoint.sh ./

RUN chmod +x /codesignal/entrypoint.sh && \
    mkdir -p \
        /codesignal/data/chrome_profiles \
        /codesignal/data/screenshots \
        /codesignal/data/screenshots_login && \
    touch /codesignal/data/akun.txt

VOLUME ["/codesignal/data"]

ENTRYPOINT ["./entrypoint.sh"]
CMD ["help"]