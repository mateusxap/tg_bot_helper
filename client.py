import win32gui
import win32con
import win32api
import win32console
import ctypes
from ctypes import Structure, byref, c_int
import threading
import io
import pyautogui
import logging
import tkinter as tk
import time
import platform
import json
import asyncio
import websockets
from functools import partial

# Более компактная настройка логирования с ротацией файлов
logging.basicConfig(
    level=logging.INFO,  # Меняем на INFO вместо DEBUG для снижения нагрузки
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("client.log", maxBytes=1024 * 1024, backupCount=2),  # Ограничиваем размер лог-файла
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("HelperClient")

# Глобальные переменные
current_id = None  # введённый ID
current_message = ""  # текст, который будет отображаться в оверлее
overlay_hwnd = None  # дескриптор оверлейного окна
root = None  # окно Tkinter для ввода ID
ws_connection = None  # Глобальная ссылка на активное соединение
reconnect_delay = 1  # Начальная задержка для переподключения (секунды)
max_reconnect_delay = 30  # Максимальная задержка для переподключения (секунды)
connection_active = False  # Флаг активного соединения

# Константы для Display Affinity
WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011  # Прозрачность при захвате (Windows 10 2004+)

# Настройки для скриншотов
SCREENSHOT_QUALITY = 80  # Качество JPG (от 1 до 100)
SCREENSHOT_FORMAT = "JPEG"  # Формат сжатия (JPEG быстрее PNG)


class MARGINS(Structure):
    _fields_ = [
        ("cxLeftWidth", c_int),
        ("cxRightWidth", c_int),
        ("cyTopHeight", c_int),
        ("cyBottomHeight", c_int)
    ]


########################################
# Вспомогательные функции
########################################
def get_windows_build():
    """Получает номер сборки Windows для определения возможностей API"""
    version = platform.version()
    try:
        build = int(version.split('.')[-1])
        return build
    except (ValueError, IndexError):
        return 0  # Если не удалось определить версию, возвращаем 0


def save_id_to_file(id_value):
    """Сохраняет ID в файл для автоматического использования при следующем запуске"""
    try:
        with open("client_id.txt", "w") as f:
            f.write(id_value)
        logger.info(f"ID {id_value} сохранен в файл")
    except Exception as e:
        logger.error(f"Ошибка сохранения ID: {e}")


def load_id_from_file():
    """Загружает ID из файла, если он существует"""
    try:
        with open("client_id.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.error(f"Ошибка загрузки ID: {e}")
        return None


def take_optimized_screenshot():
    """Создает оптимизированный скриншот"""
    try:
        # Используем pyautogui для получения скриншота
        screenshot = pyautogui.screenshot()

        # Используем буфер в памяти для сохранения скриншота
        img_io = io.BytesIO()

        # Сохраняем в формате JPEG с указанным качеством для оптимизации размера
        screenshot.save(img_io, format=SCREENSHOT_FORMAT, quality=SCREENSHOT_QUALITY)

        # Получаем байты изображения
        img_bytes = img_io.getvalue()
        logger.debug(f"Создан скриншот размером {len(img_bytes) / 1024:.1f} KB")
        return img_bytes
    except Exception as e:
        logger.error(f"Ошибка при создании скриншота: {e}")
        return None


########################################
# Интерфейс для ввода ID (Tkinter)
########################################
def create_gui():
    """Создает GUI для ввода ID и настройки соединения"""
    global root, current_id

    # Пытаемся загрузить сохраненный ID
    saved_id = load_id_from_file()

    root = tk.Tk()
    root.title("Helper Client")
    root.geometry("400x250")

    # Добавляем иконку в трей при минимизации
    root.protocol("WM_DELETE_WINDOW", lambda: root.iconify())

    # Создаем фрейм для стилизации
    main_frame = tk.Frame(root, padx=20, pady=20)
    main_frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(main_frame, text="Введите уникальный ID:", font=("Arial", 12)).pack(pady=5)

    id_entry = tk.Entry(main_frame, width=30, font=("Arial", 12))
    id_entry.pack(pady=10)

    # Если есть сохраненный ID, используем его
    if saved_id:
        id_entry.insert(0, saved_id)

    status_label = tk.Label(main_frame, text="Статус: Ожидание подключения", font=("Arial", 10))
    status_label.pack(pady=10)

    def set_id():
        global current_id
        input_id = id_entry.get().strip()
        if input_id:
            current_id = input_id
            save_id_to_file(current_id)
            status_label.config(text=f"ID установлен: {current_id}\nЗапуск подключения...")
            # Переходим к запуску WebSocket клиента
            root.after(500, lambda: start_client_and_minimize())
        else:
            status_label.config(text="Ошибка: ID не может быть пустым")

    def start_client_and_minimize():
        """Запускает соединение и минимизирует окно"""
        # Запускаем WebSocket клиент в отдельном потоке
        threading.Thread(target=start_ws_client_thread, daemon=True).start()
        # Запускаем оверлейное окно в отдельном потоке
        threading.Thread(target=main_overlay, daemon=True).start()
        # Минимизируем окно
        root.iconify()

    # Кнопки
    button_frame = tk.Frame(main_frame)
    button_frame.pack(pady=10)

    tk.Button(button_frame, text="Подключиться", command=set_id,
              font=("Arial", 11), width=15, bg="#4CAF50", fg="white").pack(side=tk.LEFT, padx=5)

    tk.Button(button_frame, text="Выход", command=root.destroy,
              font=("Arial", 11), width=15, bg="#f44336", fg="white").pack(side=tk.LEFT, padx=5)

    # Если у нас уже есть ID в параметрах командной строки или файле, можно подключиться автоматически
    if saved_id:
        status_label.config(text=f"Найден сохраненный ID: {saved_id}\nНажмите 'Подключиться' для запуска")

    root.mainloop()


########################################
# WebSocket клиент для связи с ботом
########################################
async def ws_client():
    """Асинхронный WebSocket клиент для связи с сервером"""
    global ws_connection, connection_active, reconnect_delay

    # URL сервера (при необходимости изменить на ваш IP)
    ws_url = "ws://87.242.119.104:8765"

    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=60) as websocket:
                # Сохраняем соединение в глобальной переменной
                ws_connection = websocket
                connection_active = True
                reconnect_delay = 1  # Сбрасываем задержку при успешном подключении

                # Отправляем unique_id сразу после подключения
                await websocket.send(json.dumps({"unique_id": current_id}))
                logger.info("WebSocket соединение установлено с сервером.")

                # Обрабатываем входящие сообщения
                while True:
                    try:
                        message = await websocket.recv()

                        # Обрабатываем полученное сообщение
                        if isinstance(message, bytes):
                            logger.warning("Получены бинарные данные, но не ожидались")
                        else:
                            try:
                                command = json.loads(message)
                                action = command.get("action")

                                if action == "screenshot":
                                    logger.info("Получена команда на скриншот")
                                    # Захватываем скриншот
                                    img_bytes = take_optimized_screenshot()
                                    if img_bytes:
                                        # Отправляем бинарные данные
                                        await websocket.send(img_bytes)
                                        logger.info(f"Скриншот отправлен ({len(img_bytes) / 1024:.1f} KB)")

                                elif action == "message":
                                    text = command.get("text", "")
                                    text = text.replace('\n', ' ')
                                    logger.info(f"Получено сообщение: {text[:50]}...")
                                    global current_message
                                    current_message = text

                                    # Обновляем оверлей
                                    if overlay_hwnd:
                                        win32gui.RedrawWindow(overlay_hwnd, None, None,
                                                              win32con.RDW_INVALIDATE | win32con.RDW_UPDATENOW)

                                elif action == "reset":
                                    logger.info("Получена команда сброса текста")
                                    current_message = ""

                                    # Обновляем оверлей
                                    if overlay_hwnd:
                                        win32gui.RedrawWindow(overlay_hwnd, None, None,
                                                              win32con.RDW_INVALIDATE | win32con.RDW_UPDATENOW)

                                else:
                                    logger.warning(f"Неизвестная команда: {action}")

                            except json.JSONDecodeError:
                                logger.warning(f"Нераспознанное сообщение: {message[:50]}...")

                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("Соединение закрыто сервером")
                        break

                    except Exception as e:
                        logger.error(f"Ошибка обработки сообщения: {e}")

        except (websockets.exceptions.ConnectionError,
                websockets.exceptions.InvalidStatusCode,
                OSError) as conn_err:
            connection_active = False
            ws_connection = None
            logger.error(f"Ошибка подключения: {conn_err}")

            # Используем экспоненциальную задержку с ограничением
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

            # Пытаемся переподключиться
            logger.info(f"Попытка переподключения через {reconnect_delay} сек...")

        except Exception as e:
            connection_active = False
            ws_connection = None
            logger.error(f"Неожиданная ошибка WebSocket: {e}")
            await asyncio.sleep(reconnect_delay)


def start_ws_client_thread():
    """Запускает WebSocket клиент в отдельном потоке"""
    try:
        asyncio.run(ws_client())
    except Exception as e:
        logger.error(f"Ошибка запуска WebSocket клиента: {e}")


########################################
# Оконная процедура для оверлейного окна (Win32)
########################################
def wndProc(hWnd, msg, wParam, lParam):
    """Процедура обработки сообщений для оверлейного окна"""
    global current_message

    if msg == win32con.WM_ERASEBKGND:
        return 1

    elif msg == win32con.WM_PAINT:
        try:
            hdc, ps = win32gui.BeginPaint(hWnd)
            rect = win32gui.GetClientRect(hWnd)

            # Создаем кисть и заполняем фон
            brush = win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0))
            win32gui.FillRect(hdc, rect, brush)
            win32gui.DeleteObject(brush)

            # Настраиваем цвет текста и прозрачность фона
            win32gui.SetTextColor(hdc, win32api.RGB(169, 169, 169))  # тёмно-серый текст
            win32gui.SetBkMode(hdc, win32con.TRANSPARENT)

            # Создаем шрифт через ctypes для более оптимальной работы
            font_size = 25  # Размер шрифта в пунктах
            hfont = ctypes.windll.gdi32.CreateFontW(
                font_size,  # высота шрифта
                0,  # ширина (0 = автоматическая)
                0,  # угол наклона
                0,  # угол наклона базовой линии
                win32con.FW_NORMAL,  # вес шрифта
                False,  # курсив
                False,  # подчеркивание
                False,  # зачеркнутый
                win32con.ANSI_CHARSET,  # набор символов
                win32con.OUT_DEFAULT_PRECIS,  # точность вывода
                win32con.CLIP_DEFAULT_PRECIS,  # точность обрезки
                win32con.DEFAULT_QUALITY,  # качество
                win32con.DEFAULT_PITCH | win32con.FF_DONTCARE,  # шаг и семейство
                "Arial"  # имя шрифта
            )

            # Выбираем шрифт и рисуем текст
            old_font = win32gui.SelectObject(hdc, hfont)
            flags = win32con.DT_CENTER | win32con.DT_WORDBREAK

            # Добавляем статус соединения
            display_text = current_message
            if not connection_active:
                status = "[НЕТ СОЕДИНЕНИЯ]"
                if display_text:
                    display_text = f"{status} {display_text}"
                else:
                    display_text = status

            win32gui.DrawText(hdc, display_text, -1, rect, flags)

            # Освобождаем ресурсы
            win32gui.SelectObject(hdc, old_font)
            ctypes.windll.gdi32.DeleteObject(hfont)
            win32gui.EndPaint(hWnd, ps)
            return 0

        except Exception as e:
            logger.error(f"Ошибка отрисовки текста: {e}")
            return 0

    elif msg == win32con.WM_DESTROY:
        win32gui.PostQuitMessage(0)
        return 0

    else:
        return win32gui.DefWindowProc(hWnd, msg, wParam, lParam)


########################################
# Функция для периодического поддержания TopMost
########################################
def maintain_topmost(hwnd):
    """Периодически переустанавливает окно на topmost для гарантии видимости"""
    while True:
        try:
            if hwnd and win32gui.IsWindow(hwnd):
                win32gui.SetWindowPos(
                    hwnd,
                    win32con.HWND_TOPMOST,
                    0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
                )
            else:
                # Если окно больше не существует, выходим из цикла
                break
        except Exception as e:
            logger.error(f"Ошибка поддержания topmost: {e}")

        # Оптимизируем частоту обновления для уменьшения нагрузки на CPU
        time.sleep(0.5)  # Каждые 500 мс вместо 100 мс


########################################
# Функция создания оверлейного окна (Win32)
########################################
def main_overlay():
    """Создает прозрачное оверлейное окно для отображения сообщений"""
    global overlay_hwnd

    # Получаем хендл текущего модуля
    hInstance = win32api.GetModuleHandle(None)

    # Определяем имя класса окна
    className = "HelperClientOverlayClass"

    # Создаем класс окна
    wc = win32gui.WNDCLASS()
    wc.hInstance = hInstance
    wc.lpszClassName = className
    wc.lpfnWndProc = wndProc
    wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    wc.hbrBackground = 0

    try:
        # Регистрируем класс окна
        atom = win32gui.RegisterClass(wc)
    except Exception as e:
        logger.error(f"Ошибка при регистрации класса окна: {e}")
        return

    # Получаем размеры экрана
    screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    overlay_height = 45  # Высота оверлея

    # Пытаемся создать окно с несколькими попытками в случае ошибки
    max_attempts = 3
    attempt = 0

    while attempt < max_attempts:
        try:
            # Добавляем флаги WS_EX_LAYERED и WS_EX_TRANSPARENT чтобы окно было клика-прозрачным
            extended_style = (win32con.WS_EX_TOOLWINDOW |
                              win32con.WS_EX_NOACTIVATE |
                              win32con.WS_EX_LAYERED |
                              win32con.WS_EX_TRANSPARENT)

            # Создаем окно
            overlay_hwnd = win32gui.CreateWindowEx(
                extended_style,
                className,
                "Helper Overlay",
                win32con.WS_POPUP | win32con.WS_VISIBLE,
                0, screen_height - overlay_height,
                screen_width, overlay_height,
                0, 0, hInstance, None
            )

            # Устанавливаем прозрачность
            win32gui.SetLayeredWindowAttributes(overlay_hwnd, 0, 200, win32con.LWA_ALPHA)  # Немного прозрачности

            # Устанавливаем позицию окна на Z-order и позиционируем внизу экрана
            win32gui.SetWindowPos(
                overlay_hwnd,
                win32con.HWND_TOPMOST,
                0, screen_height - overlay_height,
                screen_width, overlay_height,
                0
            )

            # Запускаем поток для поддержания TopMost
            threading.Thread(target=maintain_topmost, args=(overlay_hwnd,), daemon=True).start()

            # Применяем прозрачность через DwmExtendFrameIntoClientArea
            try:
                dwmapi = ctypes.windll.dwmapi
                margins = MARGINS(-1, -1, -1, -1)
                result = dwmapi.DwmExtendFrameIntoClientArea(overlay_hwnd, byref(margins))
                if result != 0:
                    logger.warning(f"DwmExtendFrameIntoClientArea failed, code: {result}")
            except Exception as e:
                logger.warning(f"Ошибка DwmExtendFrameIntoClientArea: {e}")

            # Устанавливаем Display Affinity с проверкой версии Windows
            try:
                user32 = ctypes.windll.user32
                build_number = get_windows_build()
                affinity = WDA_EXCLUDEFROMCAPTURE if build_number >= 19041 else WDA_MONITOR
                result = user32.SetWindowDisplayAffinity(overlay_hwnd, affinity)
                if result == 0:
                    logger.warning("SetWindowDisplayAffinity failed")
            except Exception as e:
                logger.warning(f"Ошибка SetWindowDisplayAffinity: {e}")

            # Запускаем цикл сообщений
            win32gui.PumpMessages()
            break  # Если PumpMessages завершился нормально, выходим из цикла

        except Exception as e:
            logger.error(f"Ошибка создания оверлейного окна (попытка {attempt + 1}/{max_attempts}): {e}")
            attempt += 1
            time.sleep(1)  # Задержка перед повторной попыткой


def hide_console():
    """Скрывает консольное окно."""
    try:
        console_window = win32console.GetConsoleWindow()
        if console_window:
            win32gui.ShowWindow(console_window, win32con.SW_HIDE)
    except Exception as e:
        logger.error(f"Ошибка при скрытии консоли: {e}")


def setup_system_tray():
    """Настраивает иконку в системном трее"""
    # Эта функция добавляется для будущего развития
    # В текущей версии без использования дополнительных библиотек
    pass


########################################
# Точка входа
########################################
def main():
    """Основная функция программы"""
    try:
        # Скрываем консоль сразу после запуска
        hide_console()

        # Запускаем GUI для ввода ID
        create_gui()

        # Проверяем, был ли установлен ID
        if not current_id:
            logger.warning("ID не задан. Выход.")
            return

        # После установки current_id запускаем WebSocket клиент
        # и оверлейное окно в GUI, а не здесь

    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()