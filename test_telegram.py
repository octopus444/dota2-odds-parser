import asyncio
from telegram import Bot

async def send_test():
    # Токен бота
    bot = Bot("7849937358:AAH5po6B6rMcJtedJeEK-1yiZf-1i7oTi3E")
    
    # Отправить сообщение в оба канала
    try:
        await bot.send_message(chat_id=-1002639607167, text="🔄 Тест отправки - канал ранней линии")
        print("Сообщение в канал ранней линии отправлено успешно")
    except Exception as e:
        print(f"Ошибка отправки в канал ранней линии: {e}")
    
    try:
        await bot.send_message(chat_id=-1002610553643, text="🔄 Тест отправки - канал пеленгатора")
        print("Сообщение в канал пеленгатора отправлено успешно")
    except Exception as e:
        print(f"Ошибка отправки в канал пеленгатора: {e}")

if __name__ == "__main__":
    asyncio.run(send_test())
