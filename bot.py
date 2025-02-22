import uuid
import time
import threading
import requests
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = '7953381626:AAEoiJqZwSWY3atm5yS0V-UC6KLt-wruULk'

# Словари для хранения данных
user_ids = {}          # chat_id -> unique_id
last_request_time = {} # chat_id -> время последнего запроса
client_mapping = {}    # unique_id -> client_url

# Определение клавиатуры с кнопками
KEYBOARD = ReplyKeyboardMarkup(
    [['/start', '/screen', '/help']],
    resize_keyboard=True,
    one_time_keyboard=False
)

class RegistrationHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/register_client':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
            except Exception:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Invalid JSON'}).encode('utf-8'))
                return

            unique_id = data.get('unique_id')
            client_url = data.get('client_url')
            if unique_id and client_url:
                client_mapping[unique_id] = client_url
                logging.info(f"Клиент зарегистрирован: {unique_id} -> {client_url}")
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'registered'}).encode('utf-8'))
            else:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Missing unique_id or client_url'}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def run_registration_server():
    server_address = ('0.0.0.0', 8000)
    httpd = HTTPServer(server_address, RegistrationHandler)
    logging.info("Регистрационный сервер запущен на 0.0.0.0:8000")
    httpd.serve_forever()

threading.Thread(target=run_registration_server, daemon=True).start()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    unique_id = str(uuid.uuid4())
    user_ids[chat_id] = unique_id
    await update.message.reply_text(
        f'Ваш уникальный ID: {unique_id}\n'
        'Введите этот ID в клиентское приложение.\nПосле можете писать сообщения',
        reply_markup=KEYBOARD  # Добавляем клавиатуру
    )

async def screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    current_time = time.time()

    if chat_id in last_request_time and (current_time - last_request_time[chat_id] < 0.5):
        await update.message.reply_text('Подождите перед следующим запросом.', reply_markup=KEYBOARD)
        return

    if chat_id not in user_ids:
        await update.message.reply_text('Сначала выполните команду /start.', reply_markup=KEYBOARD)
        return

    unique_id = user_ids[chat_id]
    client_url = client_mapping.get(unique_id)
    if not client_url:
        await update.message.reply_text('Клиент не зарегистрирован.', reply_markup=KEYBOARD)
        return

    try:
        response = requests.get(f'{client_url}/screenshot/{unique_id}', timeout=5)
        if response.status_code == 200:
            await context.bot.send_photo(chat_id=chat_id, photo=response.content)
            last_request_time[chat_id] = current_time
        else:
            await update.message.reply_text(f'Ошибка при запросе скриншота: {response.status_code}', reply_markup=KEYBOARD)
    except requests.exceptions.RequestException as e:
        await update.message.reply_text(f'Не удалось подключиться к клиенту: {str(e)}', reply_markup=KEYBOARD)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Информация о боте:\n'
        '/start - Получить уникальный ID\n'
        '/screen - Запросить скриншот\n'
        '/help - Показать эту справку',
        reply_markup=KEYBOARD
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_ids:
        await update.message.reply_text('Сначала выполните команду /start.', reply_markup=KEYBOARD)
        return

    unique_id = user_ids[chat_id]
    client_url = client_mapping.get(unique_id)
    if not client_url:
        await update.message.reply_text('Клиент не зарегистрирован.', reply_markup=KEYBOARD)
        return

    text = update.message.text
    try:
        response = requests.post(f'{client_url}/message', data=text.encode('utf-8'), timeout=5)
        if response.status_code == 200:
            await update.message.reply_text('Текст отправлен клиенту.', reply_markup=KEYBOARD)
        else:
            await update.message.reply_text('Ошибка при отправке текста.', reply_markup=KEYBOARD)
    except requests.exceptions.RequestException:
        await update.message.reply_text('Не удалось подключиться к клиенту.', reply_markup=KEYBOARD)

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('screen', screen))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.run_polling()

if __name__ == '__main__':
    main()