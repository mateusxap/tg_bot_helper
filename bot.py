import uuid
import time
import threading
import json
import logging
import asyncio
import websockets
from collections import defaultdict
from datetime import datetime, timedelta

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TelegramBot")

# Токен бота (при необходимости поменять)
TOKEN = '7953381626:AAEoiJqZwSWY3atm5yS0V-UC6KLt-wruULk'

# Константы и настройки
ADMIN_PASSWORD = "0000"
SCREENSHOT_TIMEOUT = 5  # секунды для ожидания скриншота
MIN_REQUEST_INTERVAL = 0.5  # минимальный интервал между запросами
WS_PING_INTERVAL = 30  # интервал пинга в секундах
WS_INACTIVE_TIMEOUT = 3600  # время в секундах для удаления неактивных соединений (1 час)

# Словари для хранения данных с более эффективным управлением ресурсами
user_ids = {}  # chat_id -> unique_id
last_request_time = {}  # chat_id -> время последнего запроса
ws_connections = {}  # unique_id -> (websocket, last_activity_time)
screenshot_futures = {}  # unique_id -> asyncio.Future

# Состояния для ConversationHandler
PASSWORD = 0

# Определяем клавиатуру с кнопками
KEYBOARD = ReplyKeyboardMarkup(
    [['/start', '/screen', '/reset'],
     ['/help']],
    resize_keyboard=True,
    one_time_keyboard=False
)


# Класс для отслеживания статистики и лимитов
class Statistics:
    def __init__(self):
        self.screenshot_requests = 0
        self.message_requests = 0
        self.failed_requests = 0
        self.active_connections = 0
        self.rate_limited = defaultdict(int)  # chat_id -> количество ограничений

    def update_connections(self, count):
        self.active_connections = count

    def log_screenshot(self):
        self.screenshot_requests += 1

    def log_message(self):
        self.message_requests += 1

    def log_failure(self):
        self.failed_requests += 1

    def rate_limit(self, chat_id):
        self.rate_limited[chat_id] += 1


stats = Statistics()


########################################
# Функции управления WebSocket соединениями
########################################
async def update_connection_timestamp(unique_id):
    """Обновляет временную метку последней активности соединения"""
    if unique_id in ws_connections:
        ws, _ = ws_connections[unique_id]
        ws_connections[unique_id] = (ws, time.time())


async def check_inactive_connections():
    """Удаляет неактивные соединения"""
    while True:
        current_time = time.time()
        for unique_id in list(ws_connections.keys()):
            _, last_active = ws_connections[unique_id]
            if current_time - last_active > WS_INACTIVE_TIMEOUT:
                ws, _ = ws_connections.pop(unique_id)
                logger.info(f"Удалено неактивное соединение: {unique_id}")
                try:
                    await ws.close()
                except Exception:
                    pass

        # Обновляем статистику
        stats.update_connections(len(ws_connections))

        # Ждем перед следующей проверкой
        await asyncio.sleep(300)  # проверка каждые 5 минут


########################################
# WebSocket-сервер для регистрации клиентов и установления соединения
########################################
async def ws_handler(websocket, path=None):
    unique_id = None
    try:
        # Ожидаем, что клиент сразу после подключения отправит свой unique_id
        message = await asyncio.wait_for(websocket.recv(), timeout=10)
        try:
            data = json.loads(message)
            unique_id = data.get("unique_id")
        except Exception:
            unique_id = message.strip()

        if not unique_id:
            await websocket.send(json.dumps({"error": "unique_id required"}))
            return

        # Сохраняем соединение и время последней активности
        ws_connections[unique_id] = (websocket, time.time())
        stats.update_connections(len(ws_connections))
        logger.info(f"Клиент подключен: {unique_id}")

        # Настраиваем пинг для поддержания соединения
        ping_task = asyncio.create_task(ping_client(websocket, unique_id))

        # Обработка входящих сообщений
        async for message in websocket:
            await update_connection_timestamp(unique_id)

            if isinstance(message, bytes):
                # Если получены бинарные данные – считаем их ответом на запрос скриншота
                future = screenshot_futures.get(unique_id)
                if future and not future.done():
                    future.set_result(message)
                else:
                    logger.debug(f"Нет ожидающего запроса скриншота для {unique_id} или он уже выполнен.")
            else:
                # Можно добавить дополнительную обработку текстовых сообщений
                logger.debug(f"Получено текстовое сообщение от {unique_id}: {message[:50]}...")

    except websockets.exceptions.ConnectionClosed:
        logger.info("Соединение закрыто")
    except asyncio.TimeoutError:
        logger.warning("Тайм-аут при ожидании ID от клиента")
    except Exception as e:
        logger.error(f"Ошибка в обработчике WebSocket: {str(e)}")
    finally:
        # Удаляем соединение из словаря
        if unique_id and unique_id in ws_connections:
            del ws_connections[unique_id]
            stats.update_connections(len(ws_connections))
            logger.info(f"Клиент отключен: {unique_id}")
        try:
            if 'ping_task' in locals() and not ping_task.done():
                ping_task.cancel()
        except Exception:
            pass


async def ping_client(websocket, unique_id):
    """Отправляет периодические пинги для поддержания соединения"""
    try:
        while True:
            await asyncio.sleep(WS_PING_INTERVAL)
            if websocket.open:
                await websocket.ping()
                logger.debug(f"Пинг отправлен клиенту {unique_id}")
            else:
                break
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.debug(f"Ошибка пинга для {unique_id}: {str(e)}")


async def start_websocket_server():
    # Для удаленного сервера
    ws_server = await websockets.serve(
        ws_handler,
        '0.0.0.0',
        8765,
        ping_interval=None,  # Мы сами управляем пингами
        max_size=10 * 1024 * 1024  # 10 МБ для передачи скриншотов
    )
    logger.info("WebSocket сервер запущен на 0.0.0.0:8765")

    # Запускаем задачу для очистки неактивных соединений
    asyncio.create_task(check_inactive_connections())

    return ws_server


########################################
# Вспомогательная функция для автоматической регистрации
########################################
async def ensure_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_ids:
        unique_id = str(chat_id)[-8:]
        user_ids[chat_id] = unique_id
        await update.message.reply_text(
            f"Вы были автоматически зарегистрированы. Ваш уникальный ID: {unique_id}",
            reply_markup=KEYBOARD
        )
    return user_ids[chat_id]


async def check_rate_limit(chat_id):
    """Проверяет ограничение скорости запросов"""
    current_time = time.time()
    if chat_id in last_request_time and (current_time - last_request_time[chat_id] < MIN_REQUEST_INTERVAL):
        stats.rate_limit(chat_id)
        return True
    last_request_time[chat_id] = current_time
    return False


########################################
# Команды Telegram бота
########################################
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    unique_id = str(chat_id)[-8:]
    user_ids[chat_id] = unique_id
    await update.message.reply_text(
        f"Ваш уникальный ID: {unique_id}\n"
        "Введите этот ID в клиентское приложение.\nПосле этого можете писать сообщения",
        reply_markup=KEYBOARD
    )


async def screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # Проверка ограничения скорости
    if await check_rate_limit(chat_id):
        await update.message.reply_text("Подождите перед следующим запросом.", reply_markup=KEYBOARD)
        return

    unique_id = await ensure_registration(update, context)

    # Проверяем наличие соединения
    if unique_id not in ws_connections:
        await update.message.reply_text("Клиент не подключен через WebSocket.", reply_markup=KEYBOARD)
        return

    ws, _ = ws_connections[unique_id]

    try:
        # Создаем Future для ожидания ответа скриншота
        future = asyncio.get_event_loop().create_future()
        screenshot_futures[unique_id] = future

        # Отправляем команду на скриншот
        command = {"action": "screenshot", "unique_id": unique_id}
        await ws.send(json.dumps(command))
        await update_connection_timestamp(unique_id)

        # Ожидаем ответа от клиента
        response_data = await asyncio.wait_for(future, timeout=SCREENSHOT_TIMEOUT)

        if isinstance(response_data, bytes):
            await context.bot.send_photo(chat_id=chat_id, photo=response_data)
            stats.log_screenshot()
        else:
            await update.message.reply_text("Неверный формат данных скриншота.", reply_markup=KEYBOARD)
            stats.log_failure()
    except asyncio.TimeoutError:
        await update.message.reply_text("Тайм-аут при ожидании скриншота.", reply_markup=KEYBOARD)
        stats.log_failure()
    except Exception as e:
        await update.message.reply_text(f"Ошибка при запросе скриншота: {str(e)}", reply_markup=KEYBOARD)
        stats.log_failure()
        logger.error(f"Ошибка скриншота для {unique_id}: {str(e)}")
    finally:
        if unique_id in screenshot_futures:
            del screenshot_futures[unique_id]


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

    # Проверка ограничения скорости (менее строгая для текстовых сообщений)
    if chat_id in last_request_time and (time.time() - last_request_time[chat_id] < 0.1):
        stats.rate_limit(chat_id)
        await update.message.reply_text("Слишком много сообщений. Подождите немного.", reply_markup=KEYBOARD)
        return

    unique_id = await ensure_registration(update, context)

    # Проверяем наличие соединения
    if unique_id not in ws_connections:
        await update.message.reply_text("Клиент не подключен через WebSocket.", reply_markup=KEYBOARD)
        return

    ws, _ = ws_connections[unique_id]
    text = update.message.text

    # Обновляем время последнего запроса
    last_request_time[chat_id] = time.time()

    try:
        command = {"action": "message", "text": text, "unique_id": unique_id}
        await ws.send(json.dumps(command))
        await update_connection_timestamp(unique_id)
        await update.message.reply_text("Текст отправлен клиенту.", reply_markup=KEYBOARD)
        stats.log_message()
    except Exception as e:
        await update.message.reply_text(f"Ошибка при отправке текста: {str(e)}", reply_markup=KEYBOARD)
        stats.log_failure()
        logger.error(f"Ошибка отправки текста для {unique_id}: {str(e)}")


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

        # Создаем список задач для параллельной отправки команд сброса
        reset_tasks = []

        for unique_id, (ws, _) in ws_connections.items():
            try:
                command = {"action": "reset", "unique_id": unique_id}
                task = asyncio.create_task(ws.send(json.dumps(command)))
                reset_tasks.append((unique_id, task))
            except Exception:
                failed_resets += 1

        # Ждем выполнения всех задач
        for unique_id, task in reset_tasks:
            try:
                await task
                await update_connection_timestamp(unique_id)
                successful_resets += 1
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


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для просмотра статистики (только для админа)"""
    chat_id = update.effective_chat.id

    # Проверка пароля администратора
    if len(context.args) < 1 or context.args[0] != ADMIN_PASSWORD:
        await update.message.reply_text("Необходим пароль администратора.", reply_markup=KEYBOARD)
        return

    # Собираем статистику
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")
    stats_text = (
        f"📊 Статистика бота (на {current_time}):\n\n"
        f"Активных соединений: {stats.active_connections}\n"
        f"Запросов скриншотов: {stats.screenshot_requests}\n"
        f"Текстовых сообщений: {stats.message_requests}\n"
        f"Ошибок запросов: {stats.failed_requests}\n"
        f"Ограничений скорости: {sum(stats.rate_limited.values())}\n"
        f"\nТоп чатов с ограничениями:\n"
    )

    # Добавляем топ-5 чатов с ограничениями скорости
    top_limited = sorted(stats.rate_limited.items(), key=lambda x: x[1], reverse=True)[:5]
    for i, (chat_id, count) in enumerate(top_limited, 1):
        stats_text += f"{i}. Chat ID {chat_id}: {count} ограничений\n"

    await update.message.reply_text(stats_text, reply_markup=KEYBOARD)


########################################
# Основная функция бота
########################################
async def main_bot():
    application = Application.builder().token(TOKEN).build()

    # Добавляем ConversationHandler для команды /reset
    reset_handler = ConversationHandler(
        entry_points=[CommandHandler("reset", reset)],
        states={
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_password)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("screen", screen))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))  # Новая команда для статистики
    application.add_handler(reset_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Запускаем WebSocket-сервер в фоне
    asyncio.create_task(start_websocket_server())

    # Включаем механизм graceful shutdown
    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("Получен сигнал завершения, закрываем соединения...")
        stop_event.set()

    application.add_handler(CommandHandler("shutdown", lambda u, c: signal_handler()))

    # Запускаем Telegram-бота
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    # Ждем сигнала завершения
    await stop_event.wait()

    # Закрываем соединения
    await application.stop()
    await application.shutdown()


########################################
# Точка входа
########################################
def main():
    try:
        # Настраиваем event loop
        import nest_asyncio
        nest_asyncio.apply()

        # Устанавливаем лимиты для asyncio
        asyncio.get_event_loop().set_debug(False)

        # Запускаем бота
        asyncio.run(main_bot())
    except KeyboardInterrupt:
        print("Бот остановлен по команде пользователя")
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()