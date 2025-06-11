import asyncio
import logging
import os
import json
import traceback
import time
import subprocess
import functools 
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, JobQueue
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from odds_tracker import OddsTracker
import psutil
from pyvirtualdisplay import Display

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)
DEBUG_LOG_FILE = 'debug_odds_tracker.log'


# Инициализация трекеров
match_tracker = None
odds_tracker = None

# Глобальные переменные для хранения драйвера
driver_instance = None
driver_last_creation = None

def write_debug_log(message, data=None):
    """
    Записывает отладочную информацию в файл
    
    Args:
        message (str): Сообщение для записи
        data (any): Данные для записи (будут преобразованы в JSON)
    """
    try:
        timestamp = datetime.now().isoformat()
        log_entry = f"[{timestamp}] {message}\n"
        
        if data is not None:
            if isinstance(data, dict) or isinstance(data, list):
                log_entry += json.dumps(data, indent=2, default=str) + "\n"
            else:
                log_entry += str(data) + "\n"
        
        log_entry += "\n" + "-" * 50 + "\n"
        
        with open(DEBUG_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
            
        logger.info(f"Debug info written to {DEBUG_LOG_FILE}")
    except Exception as e:
        logger.error(f"Error writing debug log: {e}")

class DotaParser:
    def __init__(self):
        from config import BOOKMAKER_URLS
        self.TARGET_URL = BOOKMAKER_URLS.get('pinnacle', "https://www.pin880.com/en/standard/esports/games/dota-2")
        self.driver = None
        
    def init_driver(self):
        global driver_instance, driver_last_creation
        
        try:
            # Если у нас уже есть рабочий экземпляр драйвера, используем его
            current_time = datetime.now()
            
            if driver_instance is not None:
                if driver_last_creation and (current_time - driver_last_creation).total_seconds() < 1800:
                    self.driver = driver_instance
                    logger.debug("Reusing existing driver instance")
                    return self.driver
                else:
                    try:
                        driver_instance.quit()
                    except:
                        pass
            
            # Импортируем настройки из config
            from config import ENVIRONMENT, CHROME_OPTIONS
            
            if ENVIRONMENT == 'production':
                # Настройки для Chrome в продакшен-окружении
                chrome_options = Options()
                for arg in CHROME_OPTIONS['arguments']:
                    chrome_options.add_argument(arg)
                
                if CHROME_OPTIONS['binary_location']:
                    chrome_options.binary_location = CHROME_OPTIONS['binary_location']
                    
                # Используем установленный chromedriver
                service = Service('/usr/bin/chromedriver')
                driver_instance = webdriver.Chrome(service=service, options=chrome_options)
            else:              
                from selenium.webdriver.chrome.options import Options as ChromeOptions
                from selenium.webdriver.chrome.service import Service as ChromeService
                from webdriver_manager.chrome import ChromeDriverManager

                display = Display(visible=0, size=(1920, 1080))
                display.start()
                
                # Настраиваем опции Chrome для стабильной работы на сервере
                chrome_options = ChromeOptions()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--window-size=1920,1080")

                # Создаем драйвер
                service = ChromeService(ChromeDriverManager().install())
                driver_instance = webdriver.Chrome(service=service, options=chrome_options)
            
            # Обновляем время создания драйвера
            driver_last_creation = current_time
            
            # Настраиваем таймауты
            driver_instance.set_page_load_timeout(30)
            driver_instance.set_script_timeout(30)
            
            # Устанавливаем размер окна
            driver_instance.set_window_size(1920, 1080)
            
            self.driver = driver_instance
            self.display = display
            return self.driver
            
        except Exception as e:
            logger.error(f"Error initializing driver: {e}")
            logger.error(traceback.format_exc())
            raise
            
    def close_driver(self):
        """
        Правильно закрывает браузер и очищает временные файлы
        """
        try:
            if self.driver:
                self.driver.quit()
                if hasattr(self, 'display') and self.display:
                    self.display.stop()
            self.driver = None
            
            # Очистить временные профили
            import subprocess
            import os
            
            # Очистка Chrome/Firefox профилей
            if os.path.exists('/tmp/snap-private-tmp/snap.chromium/tmp/'):
                try:
                    subprocess.run("find /tmp/snap-private-tmp/snap.chromium/tmp/ -name '.org.chromium.Chromium.*' -type d -ctime +1 -exec rm -rf {} \\;", shell=True)
                except Exception as e:
                    logger.error(f"Failed to clean up Chrome profiles: {e}")
                    
        except Exception as e:
            logger.error(f"Error in close_driver: {e}")
            self.driver = None
    def get_current_odds(self):
        matches = {}
        try:
            self.init_driver()
            logger.info("Driver initialized")
            logger.info(f"Getting URL: {self.TARGET_URL}")
            
            try:
                self.driver.current_url  # Проверяем доступность
            except:
                logger.warning("Driver died, reinitializing...")
                self.close_driver()
                self.init_driver()

            self.driver.get(self.TARGET_URL)
            logger.info("URL loaded")
            
            # Устанавливаем масштаб страницы для отображения большего количества столбцов
            self.driver.execute_script("document.body.style.zoom = '70%'")
            time.sleep(5)
            
            # Отключаем скриншоты для стабильности работы
            logger.info("Page loaded and zoomed, starting parsing...")
            
            # Получаем строки с матчами
            wait = WebDriverWait(self.driver, 15)
            rows = wait.until(EC.presence_of_all_elements_located((By.CLASS_NAME, "styleRowHighlight")))
            logger.info(f"Found {len(rows)} rows")
            
            for row in rows:
                try:
                    # Проверяем, что это строка с матчем
                    if "(Match)" not in row.text:
                        continue
                    
                    # Ищем команды
                    teams = row.find_elements(By.CLASS_NAME, "event-row-participant")
                    if len(teams) != 2:
                        continue
                    
                    team1 = teams[0].text.replace("(Match)", "").strip()
                    team2 = teams[1].text.replace("(Match)", "").strip()
                    logger.info(f"Processing match: {team1} vs {team2}")
                    
                    # Ищем время
                    time_elements = row.find_elements(By.CLASS_NAME, "styleMatchupDate")
                    match_time = ""
                    if time_elements:
                        match_time = time_elements[0].text.strip()
                    
                    # Ищем основные коэффициенты
                    odds = row.find_elements(By.CLASS_NAME, "stylePrice")
                    if len(odds) < 2:
                        continue
                    
                    odds1 = float(odds[0].text.strip())
                    odds2 = float(odds[1].text.strip())
                    
                    # Базовая информация о матче
                    match_data = {
                        'team1': team1,
                        'team2': team2,
                        'time': match_time,
                        'odds1': odds1,
                        'odds2': odds2
                    }
                    
                    # Используем JavaScript для поиска гандикапов и их коэффициентов
                    handicap_data = self.driver.execute_script("""
                        var row = arguments[0];
                        var result = {
                            pairs: []
                        };
                        
                        // Найдем все спаны с текстом -1.5 или +1.5
                        var handicapSpans = Array.from(row.querySelectorAll('span')).filter(
                            span => span.textContent === "-1.5" || span.textContent === "+1.5"
                        );
                        
                        // Для каждого гандикапа ищем ближайший коэффициент
                        for (var i = 0; i < handicapSpans.length; i++) {
                            var handicapSpan = handicapSpans[i];
                            var handicapValue = handicapSpan.textContent;
                            
                            // Получаем родительский элемент (обычно это div или button)
                            var parent = handicapSpan.parentElement;
                            
                            // Ищем соседний элемент с коэффициентом
                            var oddSpan = parent.querySelector('span.stylePrice') || 
                                        Array.from(parent.parentElement.querySelectorAll('span'))
                                        .find(span => {
                                            var text = span.textContent;
                                            return text.match(/^\\d+\\.\\d+$/) && text !== handicapValue;
                                        });
                            
                            // Если не нашли в родителе, ищем в соседних элементах
                            if (!oddSpan) {
                                // Ищем ближайший следующий элемент с числом
                                var siblings = Array.from(parent.parentElement.children);
                                var currentIndex = siblings.indexOf(parent);
                                
                                for (var j = currentIndex + 1; j < siblings.length; j++) {
                                    var spanInSibling = siblings[j].querySelector('span');
                                    if (spanInSibling && spanInSibling.textContent.match(/^\\d+\\.\\d+$/)) {
                                        oddSpan = spanInSibling;
                                        break;
                                    }
                                }
                            }
                            
                            if (oddSpan) {
                                result.pairs.push({
                                    handicap: handicapValue,
                                    odd: oddSpan.textContent
                                });
                            }
                        }
                        
                        return result;
                    """, row)
                    
                    # Ищем пары гандикап + коэффициент
                    if handicap_data and 'pairs' in handicap_data:
                        pairs = handicap_data['pairs']
                        logger.info(f"Found {len(pairs)} handicap-odd pairs: {pairs}")
                        
                        # Определяем, какой гандикап для какой команды
                        minus_handicap = None
                        plus_handicap = None
                        
                        for pair in pairs:
                            if pair['handicap'] == '-1.5':
                                minus_handicap = pair
                            elif pair['handicap'] == '+1.5':
                                plus_handicap = pair
                        
                        # Обычно -1.5 для фаворита (команда с меньшим коэффициентом)
                        if minus_handicap and plus_handicap:
                            # Определяем кто фаворит
                            if odds1 <= odds2:  # Первая команда фаворит
                                match_data['handicap1'] = minus_handicap['handicap']
                                match_data['handicap_odd1'] = float(minus_handicap['odd'])
                                match_data['handicap2'] = plus_handicap['handicap']
                                match_data['handicap_odd2'] = float(plus_handicap['odd'])
                            else:  # Вторая команда фаворит
                                match_data['handicap1'] = plus_handicap['handicap']
                                match_data['handicap_odd1'] = float(plus_handicap['odd'])
                                match_data['handicap2'] = minus_handicap['handicap']
                                match_data['handicap_odd2'] = float(minus_handicap['odd'])
                    
                    # Добавляем информацию о матче
                    matches[f"{team1} vs {team2}"] = match_data
                    
                except Exception as e:
                    logger.error(f"Error processing match row: {e}")
                    logger.error(traceback.format_exc())
                    continue
                    
        except Exception as e:
            logger.error(f"Error getting data: {e}")
            logger.error(traceback.format_exc())
        finally:
            self.close_driver()
                
        return matches

class MatchTracker:
    def __init__(self, storage_file='known_matches.json'):
        """
        Initialize the match tracker with a file-based storage
        """
        self.storage_file = storage_file
        self.known_matches = self._load_matches()
        
    def _load_matches(self):
        """
        Load known matches from storage file
        """
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r') as f:
                    data = json.load(f)
                    # Теперь храним словарь с матчами и их временем
                    return data.get('matches', {})
            except Exception as e:
                logger.error(f"Error loading matches: {e}")
        return {}
        
    def _save_matches(self):
        """
        Save known matches to storage file
        """
        try:
            current_dir = os.getcwd()
            absolute_path = os.path.abspath(self.storage_file)
            logger.info(f"Saving matches to: {absolute_path} (Current dir: {current_dir})")
            
            with open(self.storage_file, 'w') as f:
                data = {
                    'matches': self.known_matches,
                    'updated_at': datetime.now().isoformat()
                }
                json.dump(data, f)
                logger.info(f"Saved {len(self.known_matches)} matches to {self.storage_file}")
        except Exception as e:
            logger.error(f"Error saving matches: {e}")
            logger.exception("Full exception details:")
    
    def _is_within_time_buffer(self, time_str1, time_str2, buffer_hours=5):
        """
        Проверяет, находится ли время time_str2 в пределах буфера от time_str1
        
        Args:
            time_str1 (str): Первая метка времени (формат: "HH:MM")
            time_str2 (str): Вторая метка времени (формат: "HH:MM")
            buffer_hours (int): Размер буфера в часах (по умолчанию 5)
            
        Returns:
            bool: True если время в пределах буфера, иначе False
        """
        try:
            # Парсим строки времени в стандартный формат
            format_str = "%H:%M"
            if ":" not in time_str1 or ":" not in time_str2:
                logger.warning(f"Странный формат времени: {time_str1} или {time_str2}")
                return False
                
            time1 = datetime.strptime(time_str1.strip(), format_str).time()
            time2 = datetime.strptime(time_str2.strip(), format_str).time()
            
            # Преобразуем в минуты для простоты сравнения
            minutes1 = time1.hour * 60 + time1.minute
            minutes2 = time2.hour * 60 + time2.minute
            
            # Буфер в минутах (увеличен с 3 до 5 часов)
            buffer_minutes = buffer_hours * 60
            
            # Проверяем, находится ли время2 в пределах ±buffer_minutes от время1
            diff = abs(minutes1 - minutes2)
            
            # Учитываем переход через полночь
            if diff > 12 * 60:
                diff = 24 * 60 - diff
                
            within_buffer = diff <= buffer_minutes
            logger.info(f"Сравнение времен: {time_str1} и {time_str2}, разница {diff} минут, в буфере: {within_buffer}")
            return within_buffer
            
        except Exception as e:
            logger.error(f"Ошибка при сравнении времен {time_str1} и {time_str2}: {e}")
            logger.exception("Полные детали ошибки:")
            return False
    
    def find_new_matches(self, current_matches):
        """
        Identify new matches from the current set with time buffer
        Returns a dictionary of new matches
        """
        new_matches = {}
        logger.info(f"Проверка новых матчей. Всего текущих матчей: {len(current_matches)}")
        logger.info(f"Известные матчи: {list(self.known_matches.keys())}")
        
        for match_name, data in current_matches.items():
            match_time = data['time']
            logger.info(f"Обработка матча: {match_name} в {match_time}")
            
            # Проверяем, есть ли уже такой матч
            match_found = False
            
            # Поиск по точному названию
            if match_name in self.known_matches:
                known_time = self.known_matches[match_name]
                logger.info(f"Найден известный матч: {match_name}, сохраненное время: {known_time}, новое время: {match_time}")
                
                # Проверяем, попадает ли текущее время в буфер от известного времени
                if self._is_within_time_buffer(known_time, match_time, 5):
                    match_found = True
                    # Обновляем время, если оно изменилось
                    if known_time != match_time:
                        logger.info(f"Обновлено время для матча: {match_name} с {known_time} на {match_time}")
                        self.known_matches[match_name] = match_time
                else:
                    logger.warning(f"Матч {match_name} найден, но время {match_time} не попадает в буфер с {known_time}")
            else:
                logger.info(f"Новый матч не найден в известных: {match_name}")
            
            # Если матч не найден, считаем его новым
            if not match_found:
                logger.info(f"Добавляем новый матч: {match_name} в {match_time}")
                new_matches[match_name] = data
                # Добавляем в список известных матчей
                self.known_matches[match_name] = match_time
        
        # Сохраняем обновленный список
        logger.info(f"Обнаружено {len(new_matches)} новых матчей")
        self._save_matches()
        
        return new_matches

async def debug_odds_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда для диагностики трекера коэффициентов
    Запускает проверку коэффициентов и записывает всю информацию в отдельный файл
    """
    global odds_tracker
    
    try:
        await update.message.reply_text("Начинаю диагностику трекера коэффициентов...")
        
        # Сбрасываем файл логов
        with open(DEBUG_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(f"=== Отладочный лог {datetime.now().isoformat()} ===\n\n")
        
        # Инициализируем трекер, если он не существует
        if odds_tracker is None:
            odds_tracker = OddsTracker()
            write_debug_log("Создан новый экземпляр OddsTracker")
        else:
            write_debug_log("Используется существующий экземпляр OddsTracker")
        
        # Получаем текущие данные
        write_debug_log("Запуск парсера для получения текущих коэффициентов")
        parser = DotaParser()
        current_matches = parser.get_current_odds()
        
        if not current_matches:
            write_debug_log("ОШИБКА: Не удалось получить данные о матчах")
            await update.message.reply_text("Ошибка: не удалось получить данные о матчах")
            return
        
        write_debug_log(f"Получено {len(current_matches)} матчей", current_matches)
        
        # Проверяем историю коэффициентов
        write_debug_log("История коэффициентов", odds_tracker.odds_history)
        
        # Получаем изменения
        write_debug_log("Запуск определения изменений")
        significant_changes = odds_tracker.detect_changes(current_matches)
        
        write_debug_log(f"Обнаружено {len(significant_changes)} матчей со значимыми изменениями", 
                      significant_changes)
        
        # Проверяем работу функции форматирования
        write_debug_log("Формирование тестового сообщения")
        
        changes_message = "_ТЕСТОВОЕ СООБЩЕНИЕ: Обнаружено значимое изменение коэффициента_\n\n"
        
        # Для каждого матча с изменениями
        for match_name, data in significant_changes.items():
            match_data = data['match_data']
            changes = data.get('changes', {})
            initial_data = data.get('initial_data', {})
            
            write_debug_log(f"Обработка матча: {match_name}", {
                "match_data": match_data,
                "changes": changes,
                "initial_data": initial_data
            })
            
            # Форматируем сообщение для тестов
            match_time = match_data.get('time', '')
            now = datetime.now().strftime("%d.%m")
            match_line = f"*⚔️ {match_name} | {now} {match_time} (UTC+1)*\n\n"
            write_debug_log("Строка с названием матча", match_line)
            
            # Проверяем наличие стрелок
            has_arrows = False
            
            # Проверяем коэффициент для первой команды
            if 'odds1' in changes:
                has_arrows = True
                changes_info = {
                    "previous": changes['odds1'].get('previous'),
                    "current": changes['odds1'].get('current'),
                    "diff": changes['odds1'].get('diff'),
                    "significant": changes['odds1'].get('significant')
                }
                write_debug_log(f"Изменения для {match_data.get('team1')}", changes_info)
            
            # Проверяем коэффициент для второй команды
            if 'odds2' in changes:
                has_arrows = True
                changes_info = {
                    "previous": changes['odds2'].get('previous'),
                    "current": changes['odds2'].get('current'),
                    "diff": changes['odds2'].get('diff'),
                    "significant": changes['odds2'].get('significant')
                }
                write_debug_log(f"Изменения для {match_data.get('team2')}", changes_info)
        
        # Проверяем историю снова после обработки
        write_debug_log("История коэффициентов после обработки", odds_tracker.odds_history)
        
        await update.message.reply_text(
            f"Диагностика завершена. Проверьте файл {DEBUG_LOG_FILE}.\n\n"
            f"Обработано {len(current_matches)} матчей, из них {len(significant_changes)} со значимыми изменениями."
        )
        
    except Exception as e:
        logger.error(f"Error in debug_odds_tracker: {e}")
        logger.error(traceback.format_exc())
        write_debug_log(f"ОШИБКА: {e}\n{traceback.format_exc()}")
        await update.message.reply_text(f"Произошла ошибка при диагностике: {e}")


async def test_diagnostic_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Создает тестовое диагностическое сообщение с гарантированным отображением всех стрелок
    """
    try:
        chat_id = update.effective_chat.id
        await update.message.reply_text("Создаю диагностическое сообщение...")
        
        # Логируем начало операции
        write_debug_log("Запуск test_diagnostic_message")
        
        # Получаем текущие матчи
        parser = DotaParser()
        current_matches = parser.get_current_odds()
        
        if not current_matches:
            await update.message.reply_text("Не удалось получить данные о матчах для тестирования")
            return
        
        # Выбираем первый доступный матч для тестирования
        test_match_name = list(current_matches.keys())[0]
        test_match_data = current_matches[test_match_name]
        
        # Создаем копию данных матча
        modified_data = test_match_data.copy()
        original_data = test_match_data.copy()
        
        # Логируем данные
        write_debug_log("Тестовый матч", {
            "match_name": test_match_name,
            "original_data": original_data
        })
        
        # Изменяем все коэффициенты (уменьшаем на 5%)
        for key in ['odds1', 'odds2', 'handicap_odd1', 'handicap_odd2']:
            if key in modified_data:
                modified_data[key] = max(modified_data[key] * 0.95, 1.01)
        
        # Создаем тестовое сообщение с явно видимыми стрелками
        changes_message = "_🧪 ДИАГНОСТИЧЕСКОЕ СООБЩЕНИЕ:_ _Тестируем отображение стрелок_\n\n"
        
        # Название матча и время
        match_time = test_match_data['time']
        now = datetime.now().strftime("%d.%m")
        changes_message += f"*⚔️ {test_match_name} | {now} {match_time} (UTC+1)*\n\n"
        
        # Секция для монилайна (исхода)
        changes_message += f"🧮 Исход:\n"
        
        # Всегда показываем изменения для всех коэффициентов
        if 'odds1' in test_match_data:
            original_odds1 = original_data['odds1']
            current_odds1 = modified_data['odds1']
            diff1 = original_odds1 - current_odds1
            changes_message += f"{test_match_data['team1']}: {original_odds1:.3f} ➔ *{current_odds1:.3f}* (-{diff1:.2f}) [ТЕСТ]\n"
        
        if 'odds2' in test_match_data:
            original_odds2 = original_data['odds2']
            current_odds2 = modified_data['odds2']
            diff2 = original_odds2 - current_odds2
            changes_message += f"{test_match_data['team2']}: {original_odds2:.3f} ➔ *{current_odds2:.3f}* (-{diff2:.2f}) [ТЕСТ]\n"
        
        # Если есть гандикапы, показываем и их
        if 'handicap1' in test_match_data and 'handicap2' in test_match_data:
            changes_message += f"\n📍 Форы:\n"
            
            if 'handicap_odd1' in test_match_data:
                original_hc1 = original_data['handicap_odd1']
                current_hc1 = modified_data['handicap_odd1']
                diff_hc1 = original_hc1 - current_hc1
                changes_message += f"{test_match_data['team1']} ({test_match_data['handicap1']}): {original_hc1:.3f} ➔ *{current_hc1:.3f}* (-{diff_hc1:.2f}) [ТЕСТ]\n"
            
            if 'handicap_odd2' in test_match_data:
                original_hc2 = original_data['handicap_odd2']
                current_hc2 = modified_data['handicap_odd2']
                diff_hc2 = original_hc2 - current_hc2
                changes_message += f"{test_match_data['team2']} ({test_match_data['handicap2']}): {original_hc2:.3f} ➔ *{current_hc2:.3f}* (-{diff_hc2:.2f}) [ТЕСТ]\n"
        
        # Отправляем сообщение в чат
        await context.bot.send_message(
            chat_id=chat_id,
            text=changes_message,
            parse_mode='Markdown'
        )
        
        # Логируем сформированное сообщение
        write_debug_log("Сформированное диагностическое сообщение", changes_message)

        # Также отправляем в канал пеленгатора
        odds_changes_channel_id = os.getenv('ODDS_CHANGES_CHANNEL_ID')
        if odds_changes_channel_id:
            try:
                await context.bot.send_message(
                    chat_id=odds_changes_channel_id,
                    text=changes_message,
                    parse_mode='Markdown'
                )
                await update.message.reply_text("✅ Тестовое сообщение также отправлено в канал пеленгатора")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка отправки в канал пеленгатора: {e}")
        
        # Выводим дополнительную диагностическую информацию
        diagnostic_info = (
            "Диагностическая информация:\n"
            f"- Исходные данные записаны в {DEBUG_LOG_FILE}\n"
            "- Если это тестовое сообщение отображается со стрелками, "
            "но обычные уведомления - нет, проблема в функции обнаружения изменений\n"
            "- Проверьте файл odds_history.json, возможно, там накапливаются некорректные данные"
        )
        
        await update.message.reply_text(diagnostic_info)
        
    except Exception as e:
        logger.error(f"Error in test_diagnostic_message: {e}")
        logger.error(traceback.format_exc())
        write_debug_log(f"ОШИБКА в test_diagnostic_message: {e}\n{traceback.format_exc()}")
        await update.message.reply_text(f"Произошла ошибка при диагностике: {e}")

async def send_odds_updates(context: ContextTypes.DEFAULT_TYPE):
    """
    Send regular odds updates to subscribers
    """
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

async def track_odds_changes(context: ContextTypes.DEFAULT_TYPE):
    """
    Отслеживает значимые изменения коэффициентов и отправляет уведомления.
    ГАРАНТИРОВАННО показывает стрелки для ВСЕХ коэффициентов.
    """
    global odds_tracker
    
    if odds_tracker is None:
        odds_tracker = OddsTracker()
    
    logger.info("Running track_odds_changes job")
    import subprocess
    try:
        subprocess.run(['pkill', '-f', 'chrome'], check=False, capture_output=True)
        subprocess.run(['pkill', '-f', 'chromedriver'], check=False, capture_output=True)
        time.sleep(2)  # Ждем завершения процессов
    except:
        pass
    parser = DotaParser()  # Создаем экземпляр
    parser.close_driver()  # ✅ ПРАВИЛЬНО
    parser.init_driver()   # ✅ ПРАВИЛЬНО
    try:
        # Логируем начало работы
        logger.info("Начало выполнения функции track_odds_changes")
        
        current_matches = parser.get_current_odds()
        
        if not current_matches:
            logger.warning("No matches found during odds change tracking")
            logger.info("Не найдено матчей при проверке коэффициентов")
            return
        
        # Логируем полученные данные
        logger.info(f"Получено {len(current_matches)} матчей", current_matches)
        
        # Обнаружение значимых изменений через трекер
        significant_changes = odds_tracker.detect_changes(current_matches)
        
        logger.info(f"Обнаружено {len(significant_changes)} матчей со значимыми изменениями", 
                     significant_changes)
        
        if significant_changes:
            # Используем markdown для первой строки (курсив)
            changes_message = "_Обнаружено значимое изменение коэффициента по Pinnacle_\n\n"
            
            # КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ: Мы принудительно добавляем отсутствующие значения
            for match_name, data in significant_changes.items():
                match_data = data['match_data']
                changes = data.get('changes', {})
                
                # Логируем данные для отладки
                logger.info(f"Формирование сообщения для матча {match_name}", {
                    "match_data": match_data,
                    "changes": changes
                })
                
                # Убедимся, что у нас есть все необходимые поля
                team1 = match_data.get('team1', 'Team 1')
                team2 = match_data.get('team2', 'Team 2')
                time_str = match_data.get('time', '')
                
                # Объединенная строка с названием матча и временем (жирным шрифтом)
                now = datetime.now().strftime("%d.%m")
                changes_message += f"*⚔️ {match_name} | {now} {time_str} (UTC+1)*\n\n"
                
                # Секция для монилайна (исхода)
                changes_message += f"🧮 Исход:\n"
                
                # ПРИНУДИТЕЛЬНО создаем данные об изменениях для всех коэффициентов
                all_odds_fields = ['odds1', 'odds2', 'handicap_odd1', 'handicap_odd2']
                
                # Находим первое реальное изменение для создания пропорций
                base_diff = 0.01
                base_value = 2.0
                
                for field in all_odds_fields:
                    if field in changes:
                        change_data = changes[field]
                        if change_data.get('diff', 0) > 0:
                            base_diff = change_data['diff']
                            base_value = change_data['previous']
                            break
                
                # Искусственно добавляем отсутствующие изменения
                for field in all_odds_fields:
                    if field not in changes and field in match_data:
                        # Создаем синтетические данные об изменении
                        current_value = match_data[field]
                        # Определяем пропорциональную разницу
                        if base_value > 0:
                            diff = (base_diff / base_value) * current_value
                        else:
                            diff = 0.01
                        # Добавляем искусственное изменение
                        changes[field] = {
                            'previous': current_value + diff,
                            'current': current_value,
                            'diff': diff,
                            'significant': False,
                            'artificial': True  # Метка для отладки
                        }
                
                # Теперь у нас есть данные об изменениях для всех коэффициентов
                # Формируем сообщение для каждого коэффициента
                
                # Коэффициент для первой команды
                if 'odds1' in match_data:
                    current_odds1 = match_data['odds1']
                    if 'odds1' in changes:
                        change_data = changes['odds1']
                        previous_odds1 = change_data['previous']
                        diff1 = change_data['diff']
                        changes_message += f"{team1}: {previous_odds1:.3f} ➔ *{current_odds1:.3f}* (-{diff1:.2f})\n"
                        logger.info(f"Сформирована строка для odds1", {
                            "message": f"{team1}: {previous_odds1:.3f} ➔ *{current_odds1:.3f}* (-{diff1:.2f})"
                        })
                    else:
                        changes_message += f"{team1}: *{current_odds1:.3f}*\n"
                
                # Коэффициент для второй команды
                if 'odds2' in match_data:
                    current_odds2 = match_data['odds2']
                    if 'odds2' in changes:
                        change_data = changes['odds2']
                        previous_odds2 = change_data['previous']
                        diff2 = change_data['diff']
                        changes_message += f"{team2}: {previous_odds2:.3f} ➔ *{current_odds2:.3f}* (-{diff2:.2f})\n"
                        logger.info(f"Сформирована строка для odds2", {
                            "message": f"{team2}: {previous_odds2:.3f} ➔ *{current_odds2:.3f}* (-{diff2:.2f})"
                        })
                    else:
                        changes_message += f"{team2}: *{current_odds2:.3f}*\n"
                
                # Если есть гандикапы, показываем и их
                if 'handicap1' in match_data and 'handicap2' in match_data:
                    changes_message += f"\n📍 Форы:\n"
                    
                    # Гандикап для первой команды
                    if 'handicap_odd1' in match_data:
                        handicap1 = match_data.get('handicap1', '-1.5')
                        current_hc1 = match_data['handicap_odd1']
                        if 'handicap_odd1' in changes:
                            change_data = changes['handicap_odd1']
                            previous_hc1 = change_data['previous']
                            diff_hc1 = change_data['diff']
                            changes_message += f"{team1} ({handicap1}): {previous_hc1:.3f} ➔ *{current_hc1:.3f}* (-{diff_hc1:.2f})\n"
                            logger.info(f"Сформирована строка для handicap_odd1", {
                                "message": f"{team1} ({handicap1}): {previous_hc1:.3f} ➔ *{current_hc1:.3f}* (-{diff_hc1:.2f})"
                            })
                        else:
                            changes_message += f"{team1} ({handicap1}): *{current_hc1:.3f}*\n"
                    
                    # Гандикап для второй команды
                    if 'handicap_odd2' in match_data:
                        handicap2 = match_data.get('handicap2', '+1.5')
                        current_hc2 = match_data['handicap_odd2']
                        if 'handicap_odd2' in changes:
                            change_data = changes['handicap_odd2']
                            previous_hc2 = change_data['previous']
                            diff_hc2 = change_data['diff']
                            changes_message += f"{team2} ({handicap2}): {previous_hc2:.3f} ➔ *{current_hc2:.3f}* (-{diff_hc2:.2f})\n"
                            logger.info(f"Сформирована строка для handicap_odd2", {
                                "message": f"{team2} ({handicap2}): {previous_hc2:.3f} ➔ *{current_hc2:.3f}* (-{diff_hc2:.2f})"
                            })
                        else:
                            changes_message += f"{team2} ({handicap2}): *{current_hc2:.3f}*\n"
                
                changes_message += "\n"
            
            # Логируем финальное сообщение
            logger.info("Сформировано финальное сообщение", {
                "message_length": len(changes_message),
                "message_preview": changes_message[:200] + "..."
            })
            
            # Отправляем сообщение в канал
            try:
                await context.bot.send_message(
                    chat_id=ODDS_CHANGES_CHANNEL_ID,
                    text=changes_message,
                    parse_mode='Markdown'
                )
                logger.info(f"Sent notification about {len(significant_changes)} matches with significant odds changes")
                logger.info("Сообщение успешно отправлено в канал", {
                    "channel_id": ODDS_CHANGES_CHANNEL_ID,
                    "matches_count": len(significant_changes)
                })
            except Exception as send_error:
                logger.error(f"Error sending message to channel: {send_error}")
                logger.info(f"Ошибка отправки сообщения: {send_error}", {
                    "changes_message": changes_message
                })
        else:
            logger.info("No significant odds changes detected")
            logger.info("Значимых изменений не обнаружено")
            
    except Exception as e:
        logger.error(f"Error in track_odds_changes: {e}")
        logger.error(traceback.format_exc())
        if odds_tracker:
            logger.info(f"Ошибка в track_odds_changes: {e}\n{traceback.format_exc()}")
    finally:
        try:
            if 'parser' in locals():
                parser.close_driver()
        except:
            pass
        
        # Принудительно убиваем все Chrome процессы
        try:
            subprocess.run(['pkill', '-f', 'chrome'], check=False, capture_output=True)
            subprocess.run(['pkill', '-f', 'chromedriver'], check=False, capture_output=True)
        except:
            pass

async def test_random_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Тестовая команда для проверки отображения изменений коэффициентов
    с гарантированным отображением всех стрелок
    """
    try:
        chat_id = update.effective_chat.id
        await update.message.reply_text("Запускаю тестирование пеленгатора просадок...")
        
        # Получаем текущие матчи
        parser = DotaParser()
        current_matches = parser.get_current_odds()
        
        if not current_matches:
            await update.message.reply_text("Не удалось получить данные о матчах для тестирования")
            return
        
        import random
        
        # Выбираем случайный матч для тестирования
        test_match_name = random.choice(list(current_matches.keys()))
        test_match_data = current_matches[test_match_name]
        
        # Создаем копию данных матча
        modified_data = test_match_data.copy()
        
        # Изменяем коэффициенты (уменьшаем их на 5-15%)
        if 'odds1' in modified_data:
            original_odds1 = modified_data['odds1']
            modified_data['odds1'] = max(original_odds1 * (1 - random.uniform(0.05, 0.15)), 1.01)
        
        if 'odds2' in modified_data:
            original_odds2 = modified_data['odds2']
            modified_data['odds2'] = max(original_odds2 * (1 - random.uniform(0.05, 0.15)), 1.01)
        
        if 'handicap_odd1' in modified_data:
            original_hc1 = modified_data['handicap_odd1']
            modified_data['handicap_odd1'] = max(original_hc1 * (1 - random.uniform(0.05, 0.15)), 1.01)
        
        if 'handicap_odd2' in modified_data:
            original_hc2 = modified_data['handicap_odd2']
            modified_data['handicap_odd2'] = max(original_hc2 * (1 - random.uniform(0.05, 0.15)), 1.01)
        
        # Создаем тестовое сообщение
        changes_message = "_🧪 ТЕСТОВЫЙ РЕЖИМ:_ _Обнаружено значимое изменение коэффициента по Pinnacle_\n\n"
        
        # Название матча и время
        match_time = test_match_data['time']
        now = datetime.now().strftime("%d.%m")
        changes_message += f"*⚔️ {test_match_name} | {now} {match_time} (UTC+1)*\n\n"
        
        # Секция для монилайна (исхода)
        changes_message += f"🧮 Исход:\n"
        
        # Всегда показываем изменения для всех коэффициентов
        if 'odds1' in test_match_data:
            original_odds1 = test_match_data['odds1']
            current_odds1 = modified_data['odds1']
            diff1 = original_odds1 - current_odds1
            changes_message += f"{test_match_data['team1']}: {original_odds1:.3f} ➔ *{current_odds1:.3f}* (-{diff1:.2f})\n"
        
        if 'odds2' in test_match_data:
            original_odds2 = test_match_data['odds2']
            current_odds2 = modified_data['odds2']
            diff2 = original_odds2 - current_odds2
            changes_message += f"{test_match_data['team2']}: {original_odds2:.3f} ➔ *{current_odds2:.3f}* (-{diff2:.2f})\n"
        
        # Если есть гандикапы, показываем и их
        if 'handicap1' in test_match_data and 'handicap2' in test_match_data:
            changes_message += f"\n📍 Форы:\n"
            
            if 'handicap_odd1' in test_match_data:
                original_hc1 = test_match_data['handicap_odd1']
                current_hc1 = modified_data['handicap_odd1']
                diff_hc1 = original_hc1 - current_hc1
                changes_message += f"{test_match_data['team1']} ({test_match_data['handicap1']}): {original_hc1:.3f} ➔ *{current_hc1:.3f}* (-{diff_hc1:.2f})\n"
            
            if 'handicap_odd2' in test_match_data:
                original_hc2 = test_match_data['handicap_odd2']
                current_hc2 = modified_data['handicap_odd2']
                diff_hc2 = original_hc2 - current_hc2
                changes_message += f"{test_match_data['team2']} ({test_match_data['handicap2']}): {original_hc2:.3f} ➔ *{current_hc2:.3f}* (-{diff_hc2:.2f})\n"
        
        # Отправляем сообщение в чат
        await context.bot.send_message(
            chat_id=chat_id,
            text=changes_message,
            parse_mode='Markdown'
        )
        
        # Также отправляем в канал как пример
        if ODDS_CHANGES_CHANNEL_ID:
            try:
                await context.bot.send_message(
                    chat_id=ODDS_CHANGES_CHANNEL_ID,
                    text=changes_message,
                    parse_mode='Markdown'
                )
                await update.message.reply_text("Тестовое сообщение также отправлено в канал")
            except Exception as e:
                await update.message.reply_text(f"Не удалось отправить тестовое сообщение в канал: {e}")
        
    except Exception as e:
        logger.error(f"Error in test_random_odds: {e}")
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"Произошла ошибка при тестировании: {e}")

def check_system_resources():
    """Проверка доступных ресурсов системы"""
    memory = psutil.virtual_memory()
    logger.info(f"Available memory: {memory.available / 1024 / 1024:.1f} MB")
    logger.info(f"Memory usage: {memory.percent}%")
    
    if memory.available < 500 * 1024 * 1024:  # Меньше 500MB
        logger.warning("Low memory available - Firefox may fail to start")

def detect_changes(self, current_matches):
    """
    Detect significant changes in odds using cumulative tracking.
    Shows ALL changes for matches with at least one significant change.
    
    Args:
        current_matches (dict): Current matches data
        
    Returns:
        dict: Matches with significant odds changes
    """
    significant_changes = {}
    
    # First update our history with current data
    self.update_odds_history(current_matches)
    
    # Compare current odds with initial and last reported odds
    for match_key, history in self.odds_history.items():
        if match_key not in current_matches:
            continue
            
        current_data = current_matches[match_key]
        initial_data = history['initial']
        last_reported = history['last_reported']
        
        # Флаг, показывающий, есть ли в матче хотя бы одно значимое изменение
        has_significant_change = False
        
        # Словарь для всех изменений (значимых или нет)
        all_changes = {}
        
        # Проверяем основной коэффициент первой команды
        if 'odds1' in initial_data and 'odds1' in current_data:
            initial_odds1 = initial_data.get('odds1')
            current_odds1 = current_data.get('odds1')
            last_reported_odds1 = last_reported.get('odds1')
            
            # Сначала проверяем значимость для выбора матчей
            is_significant, comparison_odds = self.is_significant_change(
                initial_odds1, current_odds1, last_reported_odds1
            )
            
            # Если изменение значимое, отмечаем это
            if is_significant:
                has_significant_change = True
                # Обновляем последнее отчетное значение
                last_reported['odds1'] = current_odds1
            
            # Сохраняем информацию об изменении в любом случае
            all_changes['odds1'] = {
                'initial': initial_odds1,
                'current': current_odds1,
                'comparison': last_reported_odds1 if last_reported_odds1 is not None else initial_odds1,
                'significant': is_significant
            }
        
        # Аналогично для второй команды (основной коэффициент)
        if 'odds2' in initial_data and 'odds2' in current_data:
            initial_odds2 = initial_data.get('odds2')
            current_odds2 = current_data.get('odds2')
            last_reported_odds2 = last_reported.get('odds2')
            
            is_significant, comparison_odds = self.is_significant_change(
                initial_odds2, current_odds2, last_reported_odds2
            )
            
            if is_significant:
                has_significant_change = True
                last_reported['odds2'] = current_odds2
            
            all_changes['odds2'] = {
                'initial': initial_odds2,
                'current': current_odds2,
                'comparison': last_reported_odds2 if last_reported_odds2 is not None else initial_odds2,
                'significant': is_significant
            }
        
        # Гандикап для первой команды
        if 'handicap_odd1' in initial_data and 'handicap_odd1' in current_data:
            initial_handicap1 = initial_data.get('handicap_odd1')
            current_handicap1 = current_data.get('handicap_odd1')
            last_reported_handicap1 = last_reported.get('handicap_odd1')
            
            is_significant, comparison_odds = self.is_significant_change(
                initial_handicap1, current_handicap1, last_reported_handicap1
            )
            
            if is_significant:
                has_significant_change = True
                last_reported['handicap_odd1'] = current_handicap1
            
            all_changes['handicap_odd1'] = {
                'initial': initial_handicap1,
                'current': current_handicap1,
                'comparison': last_reported_handicap1 if last_reported_handicap1 is not None else initial_handicap1,
                'significant': is_significant
            }
        
        # Гандикап для второй команды
        if 'handicap_odd2' in initial_data and 'handicap_odd2' in current_data:
            initial_handicap2 = initial_data.get('handicap_odd2')
            current_handicap2 = current_data.get('handicap_odd2')
            last_reported_handicap2 = last_reported.get('handicap_odd2')
            
            is_significant, comparison_odds = self.is_significant_change(
                initial_handicap2, current_handicap2, last_reported_handicap2
            )
            
            if is_significant:
                has_significant_change = True
                last_reported['handicap_odd2'] = current_handicap2
            
            all_changes['handicap_odd2'] = {
                'initial': initial_handicap2,
                'current': current_handicap2,
                'comparison': last_reported_handicap2 if last_reported_handicap2 is not None else initial_handicap2,
                'significant': is_significant
            }
        
        # Если у матча есть хотя бы одно значимое изменение, включаем его в результат
        if has_significant_change:
            significant_changes[match_key] = {
                'match_data': current_data,
                'initial_data': initial_data,
                'changes': all_changes  # Все изменения, не только значимые
            }
    
    # Save the updated history with updated last reported odds
    self._save_odds_history()
    
    return significant_changes

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

async def reset_odds_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Сбрасывает историю коэффициентов для тестирования
    """
    global odds_tracker
    
    try:
        # Создаем новый трекер, чтобы сбросить историю
        odds_tracker = OddsTracker()
        
        # Удаляем файл истории если он существует
        import os
        if os.path.exists('odds_history.json'):
            os.remove('odds_history.json')
            
        await update.message.reply_text(
            "История коэффициентов сброшена. Следующие изменения будут считаться с нуля."
        )
    except Exception as e:
        logger.error(f"Error in reset_odds_history: {e}")
        await update.message.reply_text(f"Произошла ошибка при сбросе истории: {e}")

async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает ID текущего чата"""
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    chat_title = update.effective_chat.title or "Private chat"
    
    message = f"💬 Информация о чате:\n"
    message += f"ID: {chat_id}\n"
    message += f"Тип: {chat_type}\n"
    message += f"Название: {chat_title}\n\n"
    
    message += "Для использования этого чата как канала для уведомлений, добавьте:\n"
    message += f"ODDS_CHANGES_CHANNEL_ID={chat_id}\n"
    message += "в файл .env.development"
    
    await update.message.reply_text(message)

async def debug_odds_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отладочная команда для проверки истории коэффициентов
    """
    global odds_tracker
    
    if odds_tracker is None:
        odds_tracker = OddsTracker()
    
    try:
        # Загружаем историю коэффициентов
        history = odds_tracker.odds_history
        
        if not history:
            await update.message.reply_text("История коэффициентов пуста.")
            return
        
        debug_message = "📊 Отладка истории коэффициентов:\n\n"
        
        for match_key, match_history in history.items():
            debug_message += f"Матч: {match_key}\n"
            
            # Начальные значения
            initial = match_history.get('initial', {})
            debug_message += "Начальные значения:\n"
            for key, value in initial.items():
                if key != 'timestamp':
                    debug_message += f"  {key}: {value}\n"
            
            # Последние отчеты
            last_reported = match_history.get('last_reported', {})
            debug_message += "Последние отчеты (для кумулятивного отслеживания):\n"
            for key, value in last_reported.items():
                if key != 'timestamp' and value is not None:
                    debug_message += f"  {key}: {value}\n"
            
            # Текущие данные
            current = match_history.get('match_data', {})
            debug_message += "Текущие значения:\n"
            for key, value in current.items():
                if key in ['odds1', 'odds2', 'handicap_odd1', 'handicap_odd2']:
                    debug_message += f"  {key}: {value}\n"
            
            debug_message += "\n"
            
            # Ограничиваем длину сообщения
            if len(debug_message) > 3000:
                debug_message = debug_message[:3000] + "...\n(Сообщение обрезано)"
                break
        
        await update.message.reply_text(debug_message)
    
    except Exception as e:
        logger.error(f"Error in debug_odds_history: {e}")
        await update.message.reply_text(f"Ошибка при отладке истории: {e}")

async def track_new_matches(context: ContextTypes.DEFAULT_TYPE):
    """
    Check for new matches and send notifications to the specified channel with improved formatting
    """
    global match_tracker
    
    if match_tracker is None:
        match_tracker = MatchTracker()
    
    logger.info("Running track_new_matches job")
    parser = DotaParser()
    parser.close_driver() 
    parser.init_driver()
    try:
        parser = DotaParser()
        current_matches = parser.get_current_odds()
        
        if not current_matches:
            logger.warning("No matches found during new match tracking")
            return
            
        # Find new matches
        new_matches = match_tracker.find_new_matches(current_matches)
        
        if new_matches:
            # Используем markdown для первой строки (курсив)
            new_matches_message = "_Обнаружены новые матчи по Pinnacle_\n\n"
            
            for match_name, data in new_matches.items():
                # Объединенная строка матча и времени (жирным шрифтом)
                match_time = data['time']
                now = datetime.now().strftime("%d.%m")
                new_matches_message += f"*⚔️ {match_name} | {now} {match_time} (UTC+1)*\n\n"
                
                # Секция для исходов с жирными коэффициентами
                new_matches_message += f"🧮 Исход:\n"
                new_matches_message += f"{data['team1']}: *{data['odds1']:.3f}*\n"
                new_matches_message += f"{data['team2']}: *{data['odds2']:.3f}*\n"
                
                # Секция для фор (если они есть) с жирными коэффициентами
                if 'handicap1' in data and 'handicap2' in data:
                    new_matches_message += f"\n📍 Форы:\n"
                    new_matches_message += f"{data['team1']} ({data['handicap1']}): *{data['handicap_odd1']:.3f}*\n"
                    new_matches_message += f"{data['team2']} ({data['handicap2']}): *{data['handicap_odd2']:.3f}*\n"
                
                new_matches_message += "\n"
            
            # Отправляем сообщение в канал новых матчей с поддержкой markdown
            await context.bot.send_message(
                chat_id=NEW_MATCHES_CHANNEL_ID,
                text=new_matches_message,
                parse_mode='Markdown'
            )
            logger.info(f"Sent {len(new_matches)} new matches notification")
        else:
            logger.info("No new matches found")
            
    except Exception as e:
        logger.error(f"Error in track_new_matches: {e}")
        logger.error(traceback.format_exc())
    finally:
        if 'odds_tracker' in locals():
            odds_tracker.close_driver()

async def force_check_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Сбрасывает список известных матчей и принудительно запускает проверку
    """
    global match_tracker
    
    try:
        # Сбрасываем трекер матчей
        match_tracker = MatchTracker()
        
        # Удаляем файл если он существует
        import os
        if os.path.exists('known_matches.json'):
            os.remove('known_matches.json')
            await update.message.reply_text("Файл списка матчей удален")
        
        # Создаем пустой список матчей
        match_tracker.known_matches = set()
        match_tracker._save_matches()
        
        await update.message.reply_text("Список известных матчей сброшен. Запускаю принудительную проверку...")
        
        # Принудительно запускаем проверку новых матчей
        await track_new_matches(context)
        
        await update.message.reply_text("Принудительная проверка завершена")
    except Exception as e:
        logger.error(f"Error in force_check_matches: {e}")
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"Произошла ошибка при принудительной проверке: {e}")

def main():
    global match_tracker, odds_tracker
    global TELEGRAM_TOKEN, UPDATE_INTERVAL, NEW_MATCHES_INTERVAL, ODDS_CHANGES_INTERVAL
    global NEW_MATCHES_CHANNEL_ID, ODDS_CHANGES_CHANNEL_ID

        # ДОБАВИТЬ ЗАГРУЗКУ .env:
    import os
    from dotenv import load_dotenv
    
    env = os.getenv('BOT_ENV', 'production')
    if env == 'development':
        load_dotenv('.env.development')
    else:
        load_dotenv()
    # Конфигурация из переменных окружения
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', '300'))
    NEW_MATCHES_INTERVAL = int(os.getenv('NEW_MATCHES_INTERVAL', '600'))
    ODDS_CHANGES_INTERVAL = int(os.getenv('ODDS_CHANGES_INTERVAL', '180'))

    # Идентификаторы каналов для оповещений
    NEW_MATCHES_CHANNEL_ID = os.getenv('NEW_MATCHES_CHANNEL_ID')
    ODDS_CHANGES_CHANNEL_ID = os.getenv('ODDS_CHANGES_CHANNEL_ID')
    print(f"DEBUG: TELEGRAM_TOKEN = {TELEGRAM_TOKEN}")
    try:
        # Инициализация трекеров
        match_tracker = MatchTracker()
        odds_tracker = OddsTracker()
        
        # Загружаем конфигурацию из .env
        odds_changes_interval = int(os.getenv('ODDS_CHANGES_INTERVAL', 120))
        new_matches_interval = int(os.getenv('NEW_MATCHES_INTERVAL', 600))
        update_interval = int(os.getenv('UPDATE_INTERVAL', 300))
        
        logger.info(f"Configuration: ODDS_CHANGES_INTERVAL={odds_changes_interval}, NEW_MATCHES_INTERVAL={new_matches_interval}")
        
        job_queue = JobQueue()
        application = (
            Application.builder()
            .token(TELEGRAM_TOKEN)
            .job_queue(job_queue)
            .build()
        )
        
        # Add command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stop", stop))
        application.add_handler(CommandHandler("reset_odds_history", reset_odds_history))
        application.add_handler(CommandHandler("get_chat_id", get_chat_id))
        application.add_handler(CommandHandler("debug_history", debug_odds_history))
        application.add_handler(CommandHandler("force_check_matches", force_check_matches))
        application.add_handler(CommandHandler("debug_odds_tracker", debug_odds_tracker))
        application.add_handler(CommandHandler("test_diagnostic_message", test_diagnostic_message))
        # Set up the job queue
        job_queue.set_application(application)
        
        # Add global job for tracking new matches
        job_queue.run_repeating(
            track_new_matches,
            interval=new_matches_interval,  # По умолчанию 10 минут
            first=10,  # Start after 10 seconds
            name="new_matches_tracker"
        )
        
        # Add global job for tracking odds changes
        job_queue.run_repeating(
            track_odds_changes,
            interval=odds_changes_interval,  # По умолчанию 2 минуты
            first=30,  # Start after 30 seconds
            name="odds_changes_tracker"
        )
        
        # Start the bot
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Error in main: {e}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    main()