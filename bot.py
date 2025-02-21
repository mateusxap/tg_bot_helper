import telegram
from telegram.ext import Application, CommandHandler, MessageHandler, filters  # Изменено Filters на filters
import uuid
import requests
import time

# Замените на ваш реальный токен от BotFather
TOKEN = '7953381626:AAEoiJqZwSWY3atm5yS0V-UC6KLt-wruULk'

# Адрес клиента
CLIENT_URL = 'http://127.0.0.1:5000'

# Словарь для хранения уникальных ID пользователей
user_ids = {}

# Словарь для отслеживания времени последнего запроса
last_request_time = {}

async def start(update, context):
    """
    Обработчик команды /start.
    Генерирует и отправляет уникальный ID пользователю.
    """
    chat_id = update.effective_chat.id
    unique_id = str(uuid.uuid4())
    user_ids[chat_id] = unique_id
    await update.message.reply_text(f'Ваш уникальный ID: {unique_id}\n'
                                    'Введите этот ID в клиентское приложение.')

async def screen(update, context):
    """
    Обработчик команды /screen.
    Запрашивает скриншот с клиента и отправляет его в чат.
    """
    chat_id = update.effective_chat.id
    current_time = time.time()

    if chat_id in last_request_time and (current_time - last_request_time[chat_id] < 0.5):
        await update.message.reply_text('Подождите перед следующим запросом.')
        return

    if chat_id not in user_ids:
        await update.message.reply_text('Сначала выполните команду /start.')
        return

    unique_id = user_ids[chat_id]
    try:
        response = requests.get(f'{CLIENT_URL}/screenshot/{unique_id}', timeout=5)
        if response.status_code == 200:
            await context.bot.send_photo(chat_id=chat_id, photo=response.content)
            last_request_time[chat_id] = current_time
        else:
            await update.message.reply_text('Ошибка при запросе скриншота.')
    except requests.exceptions.RequestException:
        await update.message.reply_text('Не удалось подключиться к клиенту.')

async def help_command(update, context):
    """
    Обработчик команды /help.
    Отображает справочную информацию о боте.
    """
    await update.message.reply_text('Информация о боте:\n'
                                    '/start - Получить уникальный ID\n'
                                    '/screen - Запросить скриншот\n'
                                    '/help - Показать эту справку')

async def handle_text(update, context):
    """
    Обработчик текстовых сообщений.
    Отправляет текст клиенту для отображения.
    """
    chat_id = update.effective_chat.id
    if chat_id not in user_ids:
        await update.message.reply_text('Сначала выполните команду /start.')
        return

    unique_id = user_ids[chat_id]
    text = update.message.text
    try:
        response = requests.post(f'{CLIENT_URL}/message', data=text.encode('utf-8'), timeout=5)
        if response.status_code == 200:
            await update.message.reply_text('Текст отправлен клиенту.')
        else:
            await update.message.reply_text('Ошибка при отправке текста.')
    except requests.exceptions.RequestException:
        await update.message.reply_text('Не удалось подключиться к клиенту.')

def main():
    """
    Главная функция для настройки и запуска бота.
    """
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('screen', screen))
    application.add_handler(CommandHandler('help', help_command))
    # Изменено Filters.text & ~Filters.command на filters.TEXT & ~filters.COMMAND
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.run_polling()

if __name__ == '__main__':
    main()