import os
from dotenv import load_dotenv

if os.path.exists('.env.development'):
    load_dotenv('.env.development')
else:
    load_dotenv()

ENVIRONMENT = os.getenv('ENVIRONMENT', 'development')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', '300'))

if ENVIRONMENT == 'development':
    CHROME_OPTIONS = {
        'use_manager': True,  # Для Windows используем webdriver-manager
        'binary_location': None,
        'arguments': [
            '--headless=new',
            '--disable-gpu'
        ]
    }
else:  # production
    CHROME_OPTIONS = {
        'use_manager': False,  # Для Ubuntu используем установленный chromedriver
        'binary_location': '/usr/bin/chromium-browser',
        'arguments': [
            '--headless=new',
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu'
        ]
    }

# Логи
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
if ENVIRONMENT == 'development':
    LOG_FILE = os.getenv('LOG_FILE', 'logs/dev.log')
else:
    LOG_FILE = os.getenv('LOG_FILE', '/var/log/dota_bot/bot.log')

# Администраторы бота
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '').split(',')))

# URL букмекерских контор
BOOKMAKER_URLS = {
    'pinnacle': os.getenv('PINNACLE_URL', 'https://www.pin880.com/en/standard/esports/games/dota-2')
}