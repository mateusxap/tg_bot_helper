import uuid
import time
import threading
import json
import logging
import asyncio
import websockets
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import aiohttp
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Токен бота
TOKEN = '7953381626:AAEoiJqZwSWY3atm5yS0V-UC6KLt-wruULk'

# Словари для хранения данных
USER_IDS = {}          # chat_id -> unique_id (фиксированный, 8 символов)
LAST_REQUEST_TIME = {} # chat_id -> время последнего запроса
CLIENT_MAPPING = {}    # unique_id -> client_url
WS_CONNECTIONS = {}    # unique_id -> websocket
SCREENSHOT_FUTURES = {} # unique_id -> asyncio.Future

# Пароль администратора
ADMIN_PASSWORD = "0000"

# Состояния для ConversationHandler
PASSWORD = 0

# Ограничение на одновременные запросы скриншотов
SEMAPHORE = asyncio.Semaphore(2)  # Максимум 2 одновременных запроса

# Клавиатура
KEYBOARD = ReplyKeyboardMarkup(
    [['/start', '/screen', '/reset'], ['/help']],
    resize_keyboard=True,
    one_time_keyboard=False
)

# Настройка логирования на уровне INFO
logging.basicConfig(level=logging.INFO)

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
                CLIENT_MAPPING[unique_id] = client_url
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
    httpd = ThreadingHTTPServer(server_address, RegistrationHandler)
    logging.info("Регистрационный сервер запущен на 0.0.0.0:8000")
    httpd.serve_forever()

threading.Thread(target=run_registration_server, daemon=True).start()

########################################
# WebSocket-сервер
########################################
async def ws_handler(websocket, path=None):
    try:
        message = await websocket.recv()
        try:
            data = json.loads(message)
            unique_id = data.get("unique_id")
        except Exception:
            unique_id = message.strip()
        if not unique_id:
            await websocket.send(json.dumps({"error": "unique_id required"}))
            return
        WS_CONNECTIONS[unique_id] = websocket
        logging.info(f"Клиент подключен: {unique_id}")
        async for message in websocket:
            if isinstance(message, bytes):
                future = SCREENSHOT_FUTURES.get(unique_id)
                if future and not future.done():
                    future.set_result(message)
                else:
                    logging.warning(f"Нет ожидающего запроса скриншота для {unique_id} или он уже выполнен.")
    except websockets.exceptions.ConnectionClosed:
        logging.info(f"Соединение закрыто для {unique_id}")
    finally:
        for uid, ws in list(WS_CONNECTIONS.items()):
            if ws == websocket:
                del WS_CONNECTIONS[uid]
                logging.info(f"Клиент отключен: {uid}")
                break

async def start_websocket_server():
    ws_server = await websockets.serve(ws_handler, '0.0.0.0', 8765)
    logging.info("WebSocket-сервер запущен на 0.0.0.0:8765")
    return ws_server

async def cleanup_idle_connections():
    while True:
        await asyncio.sleep(300)  # Очистка каждые 5 минут
        for unique_id, ws in list(WS_CONNECTIONS.items()):
            if ws.closed:
                del WS_CONNECTIONS[unique_id]
                logging.info(f"Очищено неактивное соединение: {unique_id}")

########################################
# Вспомогательная функция для регистрации
########################################
async def ensure_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in USER_IDS:
        unique_id = str(chat_id)[-8:]
        USER_IDS[chat_id] = unique_id
        await update.message.reply_text(
            f"Вы были автоматически зарегистрированы. Ваш уникальный ID: {unique_id}",
            reply_markup=KEYBOARD
        )
    return USER_IDS[chat_id]

########################################
# Команды Telegram-бота
########################################
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    unique_id = str(chat_id)[-8:]
    USER_IDS[chat_id] = unique_id
    await update.message.reply_text(
        f"Ваш уникальный ID: {unique_id}\n"
        "Введите этот ID в клиентское приложение.\nПосле этого можете писать сообщения",
        reply_markup=KEYBOARD
    )

async def screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    current_time = time.time()
    if chat_id in LAST_REQUEST_TIME and (current_time - LAST_REQUEST_TIME[chat_id] < 1):
        await update.message.reply_text("Подождите перед следующим запросом.", reply_markup=KEYBOARD)
        return
    unique_id = await ensure_registration(update, context)
    async with SEMAPHORE:
        ws = WS_CONNECTIONS.get(unique_id)
        if ws:
            try:
                future = asyncio.get_event_loop().create_future()
                SCREENSHOT_FUTURES[unique_id] = future
                command = {"action": "screenshot", "unique_id": unique_id}
                await ws.send(json.dumps(command))
                response_data = await asyncio.wait_for(future, timeout=5)
                if isinstance(response_data, bytes):
                    # Без сжатия, отправляем исходные данные в PNG
                    await context.bot.send_photo(chat_id=chat_id, photo=response_data)
                    LAST_REQUEST_TIME[chat_id] = current_time
                else:
                    await update.message.reply_text("Неверный формат данных скриншота.", reply_markup=KEYBOARD)
            except Exception as e:
                await update.message.reply_text(f"Ошибка при запросе скриншота: {str(e)}", reply_markup=KEYBOARD)
            finally:
                if unique_id in SCREENSHOT_FUTURES:
                    del SCREENSHOT_FUTURES[unique_id]
        else:
            client_url = CLIENT_MAPPING.get(unique_id)
            if not client_url:
                await update.message.reply_text("Клиент не зарегистрирован.", reply_markup=KEYBOARD)
                return
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{client_url}/screenshot/{unique_id}", timeout=5) as response:
                        if response.status == 200:
                            response_data = await response.read()
                            # Без сжатия, отправляем исходные данные в PNG
                            await context.bot.send_photo(chat_id=chat_id, photo=response_data)
                            LAST_REQUEST_TIME[chat_id] = current_time
                        else:
                            await update.message.reply_text(f"Ошибка при запросе скриншота: {response.status}", reply_markup=KEYBOARD)
            except Exception as e:
                await update.message.reply_text(f"Не удалось подключиться к клиенту: {str(e)}", reply_markup=KEYBOARD)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Информация о боте:\n"
        "/start - Получить уникальный ID\n"
        "/screen - Запросить скриншот\n"
        "/reset - Сбросить текст для всех активных ID (требуется пароль админа)\n"
        "/help - Показать эту справку",
        reply_markup=KEYBOARD
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    unique_id = await ensure_registration(update, context)
    ws = WS_CONNECTIONS.get(unique_id)
    text = update.message.text
    if ws:
        try:
            command = {"action": "message", "text": text, "unique_id": unique_id}
            await ws.send(json.dumps(command))
            await update.message.reply_text("Текст отправлен клиенту.", reply_markup=KEYBOARD)
        except Exception as e:
            await update.message.reply_text(f"Ошибка при отправке текста: {str(e)}", reply_markup=KEYBOARD)
    else:
        client_url = CLIENT_MAPPING.get(unique_id)
        if not client_url:
            await update.message.reply_text("Клиент не зарегистрирован.", reply_markup=KEYBOARD)
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{client_url}/message", data=text.encode("utf-8"), timeout=5) as response:
                    if response.status == 200:
                        await update.message.reply_text("Текст отправлен клиенту.", reply_markup=KEYBOARD)
                    else:
                        await update.message.reply_text("Ошибка при отправке текста.", reply_markup=KEYBOARD)
        except Exception as e:
            await update.message.reply_text(f"Не удалось подключиться к клиенту: {str(e)}", reply_markup=KEYBOARD)

# Обработчики для команды /reset
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Пожалуйста, введите пароль администратора:",
        reply_markup=ReplyKeyboardMarkup([['/cancel']], resize_keyboard=True)
    )
    return PASSWORD

async def check_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    if password == ADMIN_PASSWORD:
        successful_resets = 0
        failed_resets = 0
        for unique_id, client_url in CLIENT_MAPPING.items():
            ws = WS_CONNECTIONS.get(unique_id)
            if ws:
                try:
                    command = {"action": "reset", "unique_id": unique_id}
                    await ws.send(json.dumps(command))
                    successful_resets += 1
                except Exception:
                    failed_resets += 1
            else:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(f"{client_url}/message", data="".encode("utf-8"), timeout=5) as response:
                            if response.status == 200:
                                successful_resets += 1
                            else:
                                failed_resets += 1
                except Exception:
                    failed_resets += 1
        await update.message.reply_text(
            f"Сброс выполнен.\nУспешно: {successful_resets}\nНе удалось: {failed_resets}",
            reply_markup=KEYBOARD
        )
    else:
        await update.message.reply_text("Неверный пароль!", reply_markup=KEYBOARD)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Операция отменена.", reply_markup=KEYBOARD)
    return ConversationHandler.END

########################################
# Основная функция бота
########################################
async def main_bot():
    application = Application.builder().token(TOKEN).build()

    reset_handler = ConversationHandler(
        entry_points=[CommandHandler("reset", reset)],
        states={PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_password)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("screen", screen))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(reset_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    asyncio.create_task(start_websocket_server())
    asyncio.create_task(cleanup_idle_connections())

    await application.run_polling()

########################################
# Точка входа
########################################
def main():
    import nest_asyncio
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main_bot())

if __name__ == '__main__':
    main()