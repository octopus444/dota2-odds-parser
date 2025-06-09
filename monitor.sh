#!/bin/bash

LOG_FILE="/var/log/dota_bot/bot.log"
RESTART_NEEDED=false

# Проверка на активность процесса
if ! pgrep -f "python oddsbot.py" > /dev/null; then
    echo "Процесс бота не найден. Перезапуск..."
    RESTART_NEEDED=true
fi

# Проверка обновления логов (если лог не обновлялся более 30 минут, возможно, бот завис)
if [ -f "$LOG_FILE" ]; then
    LAST_MODIFIED=$(stat -c %Y "$LOG_FILE")
    CURRENT_TIME=$(date +%s)
    DIFF=$((CURRENT_TIME - LAST_MODIFIED))
    
    if [ $DIFF -gt 1800 ]; then
        echo "Лог не обновлялся более 30 минут. Возможно, бот завис. Перезапуск..."
        RESTART_NEEDED=true
    fi
fi

# Проверка на зомби-процессы chromedriver
if ps aux | grep -w Z | grep chromedriver > /dev/null; then
    echo "Обнаружены зомби-процессы chromedriver. Очистка..."
    # Мягкий перезапуск systemd-user-sessions может помочь с зомби
    systemctl restart systemd-user-sessions
    RESTART_NEEDED=true
fi

# Перезапуск при необходимости
if [ "$RESTART_NEEDED" = true ]; then
    systemctl restart dota-bot
    echo "Бот перезапущен в $(date)" >> /var/log/dota_bot/restarts.log
fi
