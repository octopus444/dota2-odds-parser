import asyncio
import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, JobQueue
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '7849937358:AAH5po6B6rMcJtedJeEK-1yiZf-1i7oTi3E')
UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', '300'))

class DotaParser:
    def __init__(self):
        self.TARGET_URL = "https://www.pin880.com/en/standard/esports/games/dota-2"
        self.driver = None
        
    def init_driver(self):
        try:
            chrome_options = Options()
            chrome_options.binary_location = "/usr/bin/chromium-browser"
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.page_load_strategy = 'eager'
            
            service = Service("/usr/bin/chromedriver")
            service.start()
            
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.set_page_load_timeout(30)
            self.driver.set_script_timeout(30)
            return self.driver
        except Exception as e:
            logger.error(f"Error initializing driver: {e}")
            raise
            
    def close_driver(self):
        if self.driver:
            try:
                self.driver.quit()
                os.system('pkill -f chrome')
                os.system('pkill -f chromedriver')
                os.system('rm -rf /tmp/chrome_*')
            except Exception as e:
                logger.error(f"Error closing driver: {e}")
            finally:
                self.driver = None
                
    def get_current_odds(self):
        matches = {}
        try:
            self.init_driver()
            logger.info("Driver initialized")
            logger.info(f"Getting URL: {self.TARGET_URL}")
            
            self.driver.get(self.TARGET_URL)
            logger.info("URL loaded")
            
            # Wait for elements
            wait = WebDriverWait(self.driver, 15)
            rows = wait.until(EC.presence_of_all_elements_located((By.CLASS_NAME, "styleRowHighlight")))
            logger.info(f"Found {len(rows)} rows")
            
            for row in rows:
                try:
                    # Check if it's a main match
                    if "(Match)" not in row.text:
                        continue
                    
                    teams = row.find_elements(By.CLASS_NAME, "event-row-participant")
                    if len(teams) != 2:
                        continue
                    
                    team1 = teams[0].text.replace("(Match)", "").strip()
                    team2 = teams[1].text.replace("(Match)", "").strip()
                    logger.info(f"Processing match: {team1} vs {team2}")
                    
                    # Get time
                    time_element = row.find_element(By.CLASS_NAME, "styleMatchupDate")
                    match_time = time_element.text.strip()
                    
                    # Money Line odds
                    odds = row.find_elements(By.CLASS_NAME, "stylePrice")
                    if len(odds) < 2:
                        continue
                        
                    odds1 = odds[0].text.strip()
                    odds2 = odds[1].text.strip()
                    
                    matches[f"{team1} vs {team2}"] = {
                        'team1': team1,
                        'team2': team2,
                        'time': match_time,
                        'odds1': float(odds1),
                        'odds2': float(odds2)
                    }
                        
                except Exception as e:
                    logger.error(f"Error parsing match: {e}")
                    continue
                        
        except Exception as e:
            logger.error(f"Error getting data: {e}")
        finally:
            self.close_driver()
                
        return matches

async def send_odds_updates(context: ContextTypes.DEFAULT_TYPE):
    try:
        parser = DotaParser()
        matches = parser.get_current_odds()
        
        if not matches:
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text="Не удалось получить данные о матчах"
            )
            return
            
        message = "🎮 Текущие коэффициенты:\n\n"
        for match_name, data in matches.items():
            message += f"⚔️ {match_name}\n"
            message += f"🕒 {data['time']}\n"
            message += f"📊 {data['team1']}: {data['odds1']}\n"
            message += f"📊 {data['team2']}: {data['odds2']}\n"
            
            if 'handicap1' in data and 'handicap2' in data:
                message += f"🎯 Гандикап:\n"
                message += f"   {data['team1']} ({data['handicap1']}): {data['handicap_odd1']}\n"
                message += f"   {data['team2']} ({data['handicap2']}): {data['handicap_odd2']}\n"
            message += "\n"
        
        await context.bot.send_message(
            chat_id=context.job.chat_id,
            text=message
        )
    except Exception as e:
        logger.error(f"Error in send_odds_updates: {e}")
        await context.bot.send_message(
            chat_id=context.job.chat_id,
            text="Произошла ошибка при получении обновлений"
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if context.job_queue:
            current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
            for job in current_jobs:
                job.schedule_removal()
                
            context.job_queue.run_repeating(
                send_odds_updates,
                interval=UPDATE_INTERVAL,
                first=1,
                name=str(chat_id),
                chat_id=chat_id
            )
            
            await update.message.reply_text("Бот запущен! Буду присылать обновления каждые 5 минут.")
        else:
            await update.message.reply_text("Ошибка: Job Queue не настроен")
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await update.message.reply_text("Произошла ошибка при запуске бота")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        if context.job_queue:
            current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
            for job in current_jobs:
                job.schedule_removal()
            await update.message.reply_text("Отправка обновлений остановлена.")
        else:
            await update.message.reply_text("Ошибка: Job Queue не настроен")
    except Exception as e:
        logger.error(f"Error in stop command: {e}")
        await update.message.reply_text("Произошла ошибка при остановке бота")

def main():
    try:
        job_queue = JobQueue()
        application = (
            Application.builder()
            .token(TELEGRAM_TOKEN)
            .job_queue(job_queue)
            .build()
        )
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stop", stop))
        
        job_queue.set_application(application)
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Error in main: {e}")

if __name__ == "__main__":
    main()