
FROM python:3.9-slim

RUN apt-get update && apt-get install -y wget gnupg curl unzip xvfb libxi6

# Установка Chrome (фиксированная версия)
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb

# Установка ChromeDriver (фиксированная версия)
RUN wget -q https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/133.0.6943.98/linux64/chromedriver-linux64.zip \
    && unzip chromedriver-linux64.zip \
    && mv chromedriver-linux64/chromedriver /usr/local/bin/ \
    && chmod +x /usr/local/bin/chromedriver

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["python", "oddsbot.py"]



