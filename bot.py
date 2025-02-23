import uuid
import time
import threading
import requests
import json
import logging
import asyncio
import websockets  # Убедитесь, что установлен модуль websockets (pip install websockets)
from http.server import BaseHTTPRequestHandler, HTTPServer
import socket

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Токен бота (при необходимости поменять)
TOKEN = '7953381626:AAEoiJqZwSWY3atm5yS0V-UC6KLt-wruULk'

# Словари для хранения данных
user_ids = {}          # chat_id -> unique_id (фиксированный, 8 символов)
last_request_time = {} # chat_id -> время последнего запроса
client_mapping = {}    # unique_id -> client_url

# Словарь для хранения WebSocket-соединений
ws_connections = {}    # unique_id -> websocket

# Словарь для ожидающих скриншотов (уникальный ID -> asyncio.Future)
screenshot_futures = {}

# Пароль администратора
ADMIN_PASSWORD = "0000"

# Состояния для ConversationHandler
PASSWORD = 0

# Определяем клавиатуру с кнопками
KEYBOARD = ReplyKeyboardMarkup(
    [['/start', '/screen', '/reset'],
     ['/help']],
    resize_keyboard=True,
    one_time_keyboard=False
)

########################################
# HTTP-сервер для регистрации клиентов
########################################
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
    # !!! Для удаленного сервера: при необходимости измените IP и порт
    server_address = ('0.0.0.0', 8000)
    httpd = HTTPServer(server_address, RegistrationHandler)
    logging.info("Регистрационный сервер запущен на 0.0.0.0:8000")
    httpd.serve_forever()


# Запуск HTTP-сервера в отдельном потоке
threading.Thread(target=run_registration_server, daemon=True).start()


########################################
# WebSocket-сервер для установления постоянного соединения с клиентами
########################################
async def ws_handler(websocket, path=None):
    try:
        # Ожидаем, что клиент сразу после подключения отправит свой unique_id
        message = await websocket.recv()
        try:
            data = json.loads(message)
            unique_id = data.get("unique_id")
        except Exception:
            unique_id = message.strip()
        if not unique_id:
            await websocket.send(json.dumps({"error": "unique_id required"}))
            return
        ws_connections[unique_id] = websocket
        logging.info(f"Клиент подключен: {unique_id}")
        # Обработка входящих сообщений
        async for message in websocket:
            logging.info(f"Получено сообщение от {unique_id}")
            if isinstance(message, bytes):
                # Если получены бинарные данные – считаем их ответом на запрос скриншота
                future = screenshot_futures.get(unique_id)
                if future and not future.done():
                    future.set_result(message)
                else:
                    logging.warning(f"Нет ожидающего запроса скриншота для {unique_id} или он уже выполнен.")
            else:
                # Обработка текстовых сообщений (если потребуется)
                pass
    except websockets.exceptions.ConnectionClosed:
        logging.info("Соединение закрыто")
    finally:
        # Удаляем соединение из словаря
        for uid, ws in list(ws_connections.items()):
            if ws == websocket:
                del ws_connections[uid]
                logging.info(f"Клиент отключен: {uid}")
                break


async def start_websocket_server():
    # !!! Для удаленного сервера: при необходимости измените host и port
    ws_server = await websockets.serve(ws_handler, '0.0.0.0', 8765)
    logging.info("Сервер запущен на 0.0.0.0:8765")
    return ws_server


########################################
# Команды Telegram бота
########################################
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    unique_id = str(chat_id)[-8:]
    user_ids[chat_id] = unique_id
    await update.message.reply_text(
        f'Ваш уникальный ID: {unique_id}\n'
        'Введите этот ID в клиентское приложение.\nПосле этого можете писать сообщения',
        reply_markup=KEYBOARD
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
    ws = ws_connections.get(unique_id)
    if ws:
        try:
            # Создаем Future для ожидания ответа скриншота
            future = asyncio.get_event_loop().create_future()
            screenshot_futures[unique_id] = future
            command = {"action": "screenshot", "unique_id": unique_id}
            await ws.send(json.dumps(command))
            # Ожидаем ответа от клиента (ожидается бинарное изображение PNG)
            response_data = await asyncio.wait_for(future, timeout=5)
            if isinstance(response_data, bytes):
                await context.bot.send_photo(chat_id=chat_id, photo=response_data)
                last_request_time[chat_id] = current_time
            else:
                await update.message.reply_text("Неверный формат данных скриншота.", reply_markup=KEYBOARD)
        except Exception as e:
            await update.message.reply_text(f'Ошибка при запросе скриншота: {str(e)}', reply_markup=KEYBOARD)
        finally:
            if unique_id in screenshot_futures:
                del screenshot_futures[unique_id]
    else:
        # Fallback на HTTP-запрос, если WebSocket не установлен
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
        '/reset - Сбросить текст для всех активных ID (требуется пароль админа)\n'
        '/help - Показать эту справку',
        reply_markup=KEYBOARD
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_ids:
        await update.message.reply_text('Сначала выполните команду /start.', reply_markup=KEYBOARD)
        return
    unique_id = user_ids[chat_id]
    ws = ws_connections.get(unique_id)
    text = update.message.text
    if ws:
        try:
            command = {"action": "message", "text": text, "unique_id": unique_id}
            await ws.send(json.dumps(command))
            await update.message.reply_text('Текст отправлен клиенту.', reply_markup=KEYBOARD)
        except Exception as e:
            await update.message.reply_text(f'Ошибка при отправке текста: {str(e)}', reply_markup=KEYBOARD)
    else:
        client_url = client_mapping.get(unique_id)
        if not client_url:
            await update.message.reply_text('Клиент не зарегистрирован.', reply_markup=KEYBOARD)
            return
        try:
            response = requests.post(f'{client_url}/message', data=text.encode('utf-8'), timeout=5)
            if response.status_code == 200:
                await update.message.reply_text('Текст отправлен клиенту.', reply_markup=KEYBOARD)
            else:
                await update.message.reply_text('Ошибка при отправке текста.', reply_markup=KEYBOARD)
        except requests.exceptions.RequestException:
            await update.message.reply_text('Не удалось подключиться к клиенту.', reply_markup=KEYBOARD)


# Обработчики для команды /reset
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Пожалуйста, введите пароль администратора:',
        reply_markup=ReplyKeyboardMarkup([['/cancel']], resize_keyboard=True)
    )
    return PASSWORD


async def check_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    if password == ADMIN_PASSWORD:
        successful_resets = 0
        failed_resets = 0
        for unique_id, client_url in client_mapping.items():
            ws = ws_connections.get(unique_id)
            if ws:
                try:
                    command = {"action": "reset", "unique_id": unique_id}
                    await ws.send(json.dumps(command))
                    successful_resets += 1
                except Exception:
                    failed_resets += 1
            else:
                try:
                    response = requests.post(f'{client_url}/message', data="".encode('utf-8'), timeout=5)
                    if response.status_code == 200:
                        successful_resets += 1
                    else:
                        failed_resets += 1
                except requests.exceptions.RequestException:
                    failed_resets += 1

        await update.message.reply_text(
            f'Сброс выполнен.\n'
            f'Успешно: {successful_resets}\n'
            f'Не удалось: {failed_resets}',
            reply_markup=KEYBOARD
        )
    else:
        await update.message.reply_text(
            'Неверный пароль!',
            reply_markup=KEYBOARD
        )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Операция отменена.',
        reply_markup=KEYBOARD
    )
    return ConversationHandler.END


########################################
# Основная функция бота
########################################
async def main_bot():
    application = Application.builder().token(TOKEN).build()

    # Добавляем ConversationHandler для команды /reset
    reset_handler = ConversationHandler(
        entry_points=[CommandHandler('reset', reset)],
        states={
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_password)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('screen', screen))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(reset_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Запускаем WebSocket-сервер в фоне (при необходимости измените host/port для продакшена)
    asyncio.create_task(start_websocket_server())

    # Запускаем Telegram-бота; run_polling блокирует выполнение, поэтому WebSocket уже запущен
    await application.run_polling()


########################################
# Точка входа
########################################
def main():
    # Для устранения ошибки "This event loop is already running"
    import nest_asyncio
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main_bot())


if __name__ == '__main__':
    main()