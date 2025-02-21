import telegram
from telegram.ext import Application, CommandHandler
import uuid

TOKEN = '7953381626:AAEoiJqZwSWY3atm5yS0V-UC6KLt-wruULk'  # Вставьте ваш токен здесь

# Словарь для хранения уникальных ID пользователей
user_ids = {}

async def start(update, context):
    """
    Обработчик команды /start.
    Генерирует и отправляет уникальный ID пользователю.
    """
    chat_id = update.message.chat_id
    unique_id = str(uuid.uuid4())
    user_ids[chat_id] = unique_id
    await update.message.reply_text(f'Ваш уникальный ID: {unique_id}')

async def screen(update, context):
    """
    Обработчик команды /screen.
    Заглушка для функционала скриншота.
    """
    await update.message.reply_text('Функционал скриншота находится в разработке.')

async def help_command(update, context):
    """
    Обработчик команды /help.
    Отображает справочную информацию о боте.
    """
    await update.message.reply_text('Информация о боте:\n'
                                    '/start - Получить уникальный ID\n'
                                    '/screen - Запросить скриншот\n'
                                    '/help - Показать эту справку')

def main():
    """
    Главная функция для настройки и запуска бота с использованием класса Application.
    """
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('screen', screen))
    application.add_handler(CommandHandler('help', help_command))

    application.run_polling()

if __name__ == '__main__':
    main()