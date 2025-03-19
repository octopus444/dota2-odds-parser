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
    
    def detect_significant_change(self, previous_odds, current_odds, initial_odds):
        """
        Определяет, является ли изменение значимым на основе пороговой системы
        """
        if previous_odds is None or current_odds is None:
            return False
            
        # Рассматриваем только уменьшение коэффициента (просадку)
        if current_odds >= previous_odds:
            return False
        
        # Используем предыдущий коэффициент для определения порога!
        threshold = self._get_threshold(previous_odds)
        
        # Проверяем, достаточно ли велико изменение
        diff = previous_odds - current_odds
        is_significant = diff >= threshold
        
        # Логируем результат проверки
        write_debug_log("Проверка значимости изменения", {
            "previous": previous_odds,
            "current": current_odds, 
            "initial": initial_odds,
            "diff": diff,
            "threshold": threshold,
            "is_significant": is_significant
        })
        
        return is_significant
    
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
        Обнаруживает изменения коэффициентов и определяет, какие из них значимые
        
        Args:
            current_matches (dict): Текущие данные матчей
            
        Returns:
            dict: Матчи со значимыми изменениями коэффициентов
        """
        changes_result = {}
        self._cleanup_old_matches()
        
        write_debug_log("Запуск обнаружения изменений", {
            "current_matches_count": len(current_matches),
            "history_size": len(self.odds_history),
            "current_match_names": list(current_matches.keys())
        })
        
        # Текущая временная метка
        timestamp = datetime.now().isoformat()
        
        for match_key, current_data in current_matches.items():
            # Если это новый матч, инициализируем его историю
            if match_key not in self.odds_history:
                self.odds_history[match_key] = {
                    'initial': {
                        'odds1': current_data.get('odds1'),
                        'odds2': current_data.get('odds2'),
                        'handicap_odd1': current_data.get('handicap_odd1'),
                        'handicap_odd2': current_data.get('handicap_odd2'),
                    },
                    'previous': None,
                    'match_data': current_data,
                    'last_updated': timestamp
                }
                write_debug_log(f"Новый матч добавлен в историю: {match_key}", {
                    "initial_data": self.odds_history[match_key]['initial']
                })
                continue
                
            # Получаем предыдущие данные
            history = self.odds_history[match_key]
            previous_data = history['match_data']
            initial_data = history['initial']
            
            write_debug_log(f"Обработка матча: {match_key}", {
                "current_data": current_data,
                "previous_data": previous_data,
                "initial_data": initial_data
            })
            
            # Флаг, показывающий, есть ли хоть одно значимое изменение
            has_significant_changes = False
            
            # Словарь для хранения всех изменений
            changes = {}
            
            # Проверяем изменения для основного коэффициента первой команды
            if 'odds1' in current_data and 'odds1' in previous_data:
                current_odds1 = current_data['odds1']
                previous_odds1 = previous_data['odds1']
                initial_odds1 = initial_data['odds1']
                
                # Проверяем, изменился ли коэффициент
                if current_odds1 != previous_odds1:
                    diff1 = previous_odds1 - current_odds1
                    significant1 = self.detect_significant_change(previous_odds1, current_odds1, initial_odds1)
                    
                    if significant1:
                        has_significant_changes = True
                    
                    changes['odds1'] = {
                        'previous': previous_odds1,
                        'current': current_odds1,
                        'diff': diff1,
                        'significant': significant1
                    }
                    
                    write_debug_log(f"Изменение odds1 для {match_key}", changes['odds1'])
            
            # Проверяем изменения для основного коэффициента второй команды
            if 'odds2' in current_data and 'odds2' in previous_data:
                current_odds2 = current_data['odds2']
                previous_odds2 = previous_data['odds2']
                initial_odds2 = initial_data['odds2']
                
                # Проверяем, изменился ли коэффициент
                if current_odds2 != previous_odds2:
                    diff2 = previous_odds2 - current_odds2
                    significant2 = self.detect_significant_change(previous_odds2, current_odds2, initial_odds2)
                    
                    if significant2:
                        has_significant_changes = True
                    
                    changes['odds2'] = {
                        'previous': previous_odds2,
                        'current': current_odds2,
                        'diff': diff2,
                        'significant': significant2
                    }
                    
                    write_debug_log(f"Изменение odds2 для {match_key}", changes['odds2'])
            
            # Проверяем изменения для гандикапа первой команды
            if 'handicap_odd1' in current_data and 'handicap_odd1' in previous_data:
                current_handi1 = current_data['handicap_odd1']
                previous_handi1 = previous_data['handicap_odd1']
                initial_handi1 = initial_data['handicap_odd1']
                
                # Проверяем, изменился ли коэффициент
                if current_handi1 != previous_handi1:
                    diff_handi1 = previous_handi1 - current_handi1
                    significant_handi1 = self.detect_significant_change(previous_handi1, current_handi1, initial_handi1)
                    
                    if significant_handi1:
                        has_significant_changes = True
                    
                    changes['handicap_odd1'] = {
                        'previous': previous_handi1,
                        'current': current_handi1,
                        'diff': diff_handi1,
                        'significant': significant_handi1
                    }
                    
                    write_debug_log(f"Изменение handicap_odd1 для {match_key}", changes['handicap_odd1'])
            
            # Проверяем изменения для гандикапа второй команды
            if 'handicap_odd2' in current_data and 'handicap_odd2' in previous_data:
                current_handi2 = current_data['handicap_odd2']
                previous_handi2 = previous_data['handicap_odd2']
                initial_handi2 = initial_data['handicap_odd2']
                
                # Проверяем, изменился ли коэффициент
                if current_handi2 != previous_handi2:
                    diff_handi2 = previous_handi2 - current_handi2
                    significant_handi2 = self.detect_significant_change(previous_handi2, current_handi2, initial_handi2)
                    
                    if significant_handi2:
                        has_significant_changes = True
                    
                    changes['handicap_odd2'] = {
                        'previous': previous_handi2,
                        'current': current_handi2,
                        'diff': diff_handi2,
                        'significant': significant_handi2
                    }
                    
                    write_debug_log(f"Изменение handicap_odd2 для {match_key}", changes['handicap_odd2'])
            
            # Если есть хотя бы одно значимое изменение, добавляем матч в результат
            if has_significant_changes:
                changes_result[match_key] = {
                    'match_data': current_data,
                    'initial_data': initial_data,
                    'changes': changes
                }
                
                write_debug_log(f"Матч {match_key} добавлен в результаты со значимыми изменениями", {
                    "changes": changes
                })
            
            # Обновляем историю матча
            history['previous'] = dict(history['match_data'])
            history['match_data'] = current_data
            history['last_updated'] = timestamp
        
        # Сохраняем обновленную историю
        self._save_odds_history()
        
        write_debug_log("Завершение обнаружения изменений", {
            "significant_changes_count": len(changes_result),
            "significant_match_names": list(changes_result.keys()) if changes_result else []
        })
        
        return changes_result