import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Файл для отладочной информации
DEBUG_LOG_FILE = 'debug_odds_tracker.log'

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

class OddsTracker:
    def __init__(self, storage_file='odds_history.json', retention_days=7):
        """
        Initialize the odds tracker
        
        Args:
            storage_file (str): File to store odds history
            retention_days (int): Number of days to keep match history
        """
        self.storage_file = storage_file
        self.retention_days = retention_days
        self.odds_history = self._load_odds_history()
        self.last_notified = self.load_last_notified()
        
        # Создаем новый файл логов при инициализации
        write_debug_log("Инициализирован OddsTracker", {
            "storage_file": storage_file,
            "retention_days": retention_days,
            "history_size": len(self.odds_history)
        })
        
    def _load_odds_history(self):
        """Load odds history from storage file"""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r') as f:
                    history = json.load(f)
                    write_debug_log(f"Загружена история из {self.storage_file}", {
                        "history_size": len(history),
                        "matches": list(history.keys())
                    })
                    return history
            except Exception as e:
                logger.error(f"Error loading odds history: {e}")
                write_debug_log(f"Ошибка загрузки истории: {e}")
        write_debug_log("История не найдена, создана пустая")
        return {}
        
    def _save_odds_history(self):
        """Save odds history to storage file"""
        try:
            with open(self.storage_file, 'w') as f:
                json.dump(self.odds_history, f)
                write_debug_log(f"История сохранена в {self.storage_file}", {
                    "history_size": len(self.odds_history),
                    "matches": list(self.odds_history.keys())
                })
        except Exception as e:
            logger.error(f"Error saving odds history: {e}")
            write_debug_log(f"Ошибка сохранения истории: {e}")
    
    def _get_threshold(self, odds_value):
        """
        Get the threshold for significant change based on the odds value
        
        Args:
            odds_value (float): The initial odds value
            
        Returns:
            float: The threshold value
        """
        if 1.01 <= odds_value < 1.1:
            return 0.01
        elif 1.1 <= odds_value < 1.2:
            return 0.02
        elif 1.2 <= odds_value < 1.3:
            return 0.03
        elif 1.3 <= odds_value < 1.4:
            return 0.04
        elif 1.4 <= odds_value < 1.6:
            return 0.05
        elif 1.6 <= odds_value < 1.9:
            return 0.07
        elif 1.9 <= odds_value < 2.2:
            return 0.10
        elif 2.2 <= odds_value < 2.5:
            return 0.15
        elif 2.5 <= odds_value < 3.0:
            return 0.20
        elif 3.0 <= odds_value < 4.0:
            return 0.30
        else:  # 4.0 and above
            return 0.50
    
    def is_significant_change(self, initial_value, current_value, last_reported_value):
        """
        Определяет, является ли изменение значимым на основе кумулятивного отслеживания
        Учитывает КАК ПАДЕНИЯ, ТАК И РОСТ коэффициентов
        
        Args:
            initial_value (float): Начальное значение коэффициента
            current_value (float): Текущее значение коэффициента
            last_reported_value (float): Последнее значение, для которого было отправлено уведомление
            
        Returns:
            tuple: (is_significant, new_last_reported)
                - is_significant (bool): True если изменение значимое
                - new_last_reported (float): Новое значение для last_reported
        """
        if last_reported_value is None or current_value is None:
            return False, current_value
            
        # Если текущее значение равно последнему сообщенному, нет изменения
        if current_value == last_reported_value:
            return False, last_reported_value
        
        # Рассчитываем абсолютную разницу между значениями
        diff = abs(current_value - last_reported_value)
        
        # Используем last_reported для определения порога
        threshold = self._get_threshold(last_reported_value)
        
        # Проверяем, достаточно ли велико изменение (в любом направлении)
        is_significant = diff >= threshold
        
        write_debug_log("Проверка значимости изменения (кумулятивная)", {
            "last_reported": last_reported_value,
            "current": current_value, 
            "initial": initial_value,
            "diff": diff,
            "direction": "рост" if current_value > last_reported_value else "падение",
            "threshold": threshold,
            "is_significant": is_significant
        })
        
        # Возвращаем результат и новое значение для last_reported
        # Если изменение значимое, обновляем reference value
        return is_significant, current_value if is_significant else last_reported_value
    
    def _cleanup_old_matches(self):
        """Remove matches older than retention_days from history"""
        if not self.odds_history:
            return
            
        current_time = datetime.now()
        matches_to_remove = []
        
        for match_key, history in self.odds_history.items():
            last_updated_str = history.get('last_updated')
            if not last_updated_str:
                continue
                
            try:
                last_updated = datetime.fromisoformat(last_updated_str)
                if (current_time - last_updated) > timedelta(days=self.retention_days):
                    matches_to_remove.append(match_key)
            except ValueError:
                logger.warning(f"Invalid timestamp format for match {match_key}")
        
        for match_key in matches_to_remove:
            logger.info(f"Removing old match from history: {match_key}")
            del self.odds_history[match_key]
            
        if matches_to_remove:
            write_debug_log(f"Удалено {len(matches_to_remove)} устаревших матчей", 
                         {"removed_matches": matches_to_remove})
    
    def detect_changes(self, current_matches):
        """
        Обнаруживает значимые изменения коэффициентов в обоих направлениях
        с использованием кумулятивного отслеживания
        
        Args:
            current_matches (dict): Текущие данные матчей
            
        Returns:
            dict: Матчи со значимыми изменениями коэффициентов
        """
        significant_changes = {}
        self._cleanup_old_matches()
        
        write_debug_log("Запуск обнаружения изменений", {
            "current_matches_count": len(current_matches),
            "history_size": len(self.odds_history)
        })
        
        # Текущая временная метка
        timestamp = datetime.now().isoformat()
        
        for match_key, current_data in current_matches.items():
            # Инициализация для нового матча
            if match_key not in self.odds_history:
                self.odds_history[match_key] = {
                    'initial': {
                        'odds1': current_data.get('odds1'),
                        'odds2': current_data.get('odds2'),
                        'handicap_odd1': current_data.get('handicap_odd1'),
                        'handicap_odd2': current_data.get('handicap_odd2'),
                    },
                    'last_reported': {
                        'odds1': current_data.get('odds1'),
                        'odds2': current_data.get('odds2'),
                        'handicap_odd1': current_data.get('handicap_odd1'),
                        'handicap_odd2': current_data.get('handicap_odd2'),
                    },
                    'previous': None,
                    'match_data': current_data,
                    'last_updated': timestamp
                }
                
                # Также инициализируем в last_notified
                self.last_notified.setdefault(match_key, {})
                for field in ['odds1', 'odds2', 'handicap_odd1', 'handicap_odd2']:
                    if field in current_data:
                        self.last_notified[match_key][field] = current_data.get(field)
                
                continue
                
            # Получаем данные из истории
            history = self.odds_history[match_key]
            previous_data = history['match_data']
            initial_data = history['initial']
            last_reported = history.get('last_reported', {})
            
            # Флаг значимых изменений
            has_significant_changes = False
            
            # Словарь изменений
            changes = {}
            
            # Проверяем все поля коэффициентов
            for field in ['odds1', 'odds2', 'handicap_odd1', 'handicap_odd2']:
                if field in current_data and field in initial_data:
                    current_value = current_data.get(field)
                    initial_value = initial_data.get(field)
                    
                    # Получаем значение из last_notified
                    last_reported_value = self.last_notified.get(match_key, {}).get(field)
                    if last_reported_value is None and field in current_data:
                        last_reported_value = current_value
                        self.last_notified.setdefault(match_key, {})[field] = current_value
                    
                    # Проверяем значимость изменения
                    is_significant, new_last_reported = self.is_significant_change(
                        initial_value, current_value, last_reported_value
                    )
                    
                    # Если изменение значимое
                    if is_significant:
                        has_significant_changes = True
                        # Обновляем значение в last_notified
                        self.last_notified.setdefault(match_key, {})[field] = new_last_reported
                        # Также обновляем в истории
                        last_reported[field] = new_last_reported
                    
                    # Если есть изменение между текущим и предыдущим скрапингом
                    if field in previous_data and current_value != previous_data.get(field):
                        previous_value = previous_data.get(field)
                        diff = abs(previous_value - current_value)
                        direction = 1 if current_value > previous_value else -1
                        
                        changes[field] = {
                            'previous': previous_value,
                            'current': current_value,
                            'diff': diff,
                            'direction': direction,
                            'significant': is_significant
                        }
            
            # Если есть значимые изменения, добавляем матч в результат
            if has_significant_changes:
                significant_changes[match_key] = {
                    'match_data': current_data,
                    'initial_data': initial_data,
                    'changes': changes
                }
            
            # Обновляем историю матча
            history['previous'] = dict(history['match_data'])
            history['match_data'] = current_data
            history['last_reported'] = last_reported
            history['last_updated'] = timestamp
        
        # Сохраняем обновленную историю и last_notified
        self._save_odds_history()
        self.save_last_notified()
        
        return significant_changes
    def load_last_notified(self):
        """
        Загружает последние отправленные значения для кумулятивного отслеживания
        """
        last_notified_file = 'last_notified.json'
        if os.path.exists(last_notified_file):
            try:
                with open(last_notified_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading last notified values: {e}")
        return {}

    def save_last_notified(self):
        """
        Сохраняет последние отправленные значения для кумулятивного отслеживания
        """
        last_notified_file = 'last_notified.json'
        try:
            with open(last_notified_file, 'w') as f:
                json.dump(self.last_notified, f)
        except Exception as e:
            logger.error(f"Error saving last notified values: {e}")