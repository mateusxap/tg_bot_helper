import win32gui
import win32con
import win32api
import win32console
import ctypes
from ctypes import Structure, byref, c_int
import threading
import socket
import requests
import io
import pyautogui
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import tkinter as tk
import time
import platform

logging.basicConfig(level=logging.DEBUG)

# Глобальные переменные
current_id = None         # введённый ID
current_message = ""  # текст, который будет отображаться в оверлее
overlay_hwnd = None       # дескриптор оверлейного окна
root = None               # окно Tkinter для ввода ID

# Константы для Display Affinity
WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011  # Прозрачность при захвате (Windows 10 2004+)

class MARGINS(Structure):
    _fields_ = [
        ("cxLeftWidth", c_int),
        ("cxRightWidth", c_int),
        ("cyTopHeight", c_int),
        ("cyBottomHeight", c_int)
    ]

# HTTP-сервер: обработчик запросов
class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global current_id
        logging.debug(f"Получен GET-запрос: {self.path}")
        if self.path.startswith('/screenshot/'):
            requested_id = self.path.split('/screenshot/')[1]
            logging.debug(f"Запрошенный ID: {requested_id}, текущий ID: {current_id}")
            if requested_id != current_id:
                logging.warning("Недействительный ID")
                self.send_response(403)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Invalid ID')
                return
            try:
                logging.debug("Захватываем скриншот")
                screenshot = pyautogui.screenshot()
                img_io = io.BytesIO()
                screenshot.save(img_io, 'PNG')
                img_io.seek(0)
                logging.debug("Отправляем скриншот")
                self.send_response(200)
                self.send_header('Content-type', 'image/png')
                self.end_headers()
                self.wfile.write(img_io.getvalue())
            except Exception as e:
                logging.error(f"Ошибка при захвате скриншота: {e}")
                self.send_response(500)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Screenshot failed')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global current_message, overlay_hwnd
        if self.path == '/message':
            content_length = int(self.headers.get('Content-Length', 0))
            message = self.rfile.read(content_length).decode('utf-8')
            logging.debug(f"Получено сообщение: {message}")
            current_message = message  # обновляем текст оверлея
            if overlay_hwnd:
                win32gui.RedrawWindow(overlay_hwnd, None, None, win32con.RDW_INVALIDATE | win32con.RDW_UPDATENOW)
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Message received')
        else:
            self.send_response(404)
            self.end_headers()

def start_server():
    server = HTTPServer(('0.0.0.0', 5000), RequestHandler)
    logging.info("HTTP-сервер запущен на 0.0.0.0:5000")
    server.serve_forever()

# Вспомогательные функции
def get_client_url():
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    return f'http://{local_ip}:5000'

# URL регистрации у бота (при необходимости измените)
BOT_REGISTRATION_URL = 'http://127.0.0.1:8000/register_client'

def register_client(client_id):
    client_url = get_client_url()
    try:
        response = requests.post(
            BOT_REGISTRATION_URL,
            json={'unique_id': client_id, 'client_url': client_url},
            timeout=5
        )
        if response.status_code == 200:
            logging.info(f"ID зарегистрирован: {client_id}")
        else:
            logging.error(f"Ошибка регистрации: {response.text}")
    except Exception as e:
        logging.error(f"Регистрация не удалась: {e}")

# Проверка версии Windows для выбора правильного флага Display Affinity
def get_windows_build():
    version = platform.version()
    try:
        build = int(version.split('.')[-1])
        return build
    except (ValueError, IndexError):
        return 0  # Если не удалось определить версию, возвращаем 0

########################################
# Интерфейс для ввода ID (Tkinter)
########################################
def create_gui():
    global root, current_id
    root = tk.Tk()
    root.title("Helper Client")
    root.geometry("400x200")

    tk.Label(root, text="Введите уникальный ID:").pack(pady=5)
    id_entry = tk.Entry(root, width=40)
    id_entry.pack(pady=5)

    status_label = tk.Label(root, text="ID не установлен")
    status_label.pack(pady=5)

    def set_id():
        global current_id
        current_id = id_entry.get()
        status_label.config(text=f"ID установлен: {current_id}")
        client_url = get_client_url()
        try:
            response = requests.post(
                BOT_REGISTRATION_URL,
                json={'unique_id': current_id, 'client_url': client_url},
                timeout=5
            )
            if response.status_code == 200:
                status_label.config(text=f"ID установлен и зарегистрирован: {current_id}")
                root.destroy()
            else:
                status_label.config(text=f"Ошибка регистрации: {response.text}")
        except requests.exceptions.RequestException as e:
            status_label.config(text=f"Не удалось зарегистрироваться: {e}")

    tk.Button(root, text="Подключиться", command=set_id).pack(pady=5)
    root.mainloop()

# Оконная процедура для оверлейного окна (Win32)
def wndProc(hWnd, msg, wParam, lParam):
    global current_message
    if msg == win32con.WM_ERASEBKGND:
        return 1
    elif msg == win32con.WM_PAINT:
        hdc, ps = win32gui.BeginPaint(hWnd)
        rect = win32gui.GetClientRect(hWnd)
        brush = win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0))
        win32gui.FillRect(hdc, rect, brush)
        win32gui.DeleteObject(brush)
        win32gui.SetTextColor(hdc, win32api.RGB(255, 255, 255))  # белый текст
        win32gui.SetBkMode(hdc, win32con.TRANSPARENT)

        # Создаем шрифт через ctypes, используя Windows API CreateFontW
        font_size = 25  # Установите желаемый размер шрифта в пунктах
        hfont = ctypes.windll.gdi32.CreateFontW(
            font_size,  # высота шрифта
            0,  # ширина (0 = автоматическая)
            0,  # угол наклона
            0,  # угол наклона базовой линии
            win32con.FW_NORMAL,  # вес шрифта (толщина)
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

        # Выбираем шрифт в контекст устройства
        old_font = win32gui.SelectObject(hdc, hfont)

        # Убираем DT_SINGLELINE и добавляем DT_WORDBREAK для переноса строк
        flags = win32con.DT_CENTER | win32con.DT_WORDBREAK
        win32gui.DrawText(hdc, current_message, -1, rect, flags)

        # Восстанавливаем старый шрифт и удаляем созданный
        win32gui.SelectObject(hdc, old_font)
        ctypes.windll.gdi32.DeleteObject(hfont)

        win32gui.EndPaint(hWnd, ps)
        return 0
    elif msg == win32con.WM_DESTROY:
        win32gui.PostQuitMessage(0)
        return 0
    else:
        return win32gui.DefWindowProc(hWnd, msg, wParam, lParam)

# Функция для периодического поддержания TopMost
def maintain_topmost(hwnd):
    """Периодически переустанавливает окно на topmost."""
    while True:
        try:
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOPMOST,
                0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
            )
        except Exception as e:
            logging.error(f"Ошибка поддержания topmost: {e}")
        time.sleep(0.1)  # каждые 100 мс

# Функция создания оверлейного окна (Win32)
def main_overlay():
    global overlay_hwnd
    hInstance = win32api.GetModuleHandle(None)
    className = "MyNativeOverlayWindowClass"
    wc = win32gui.WNDCLASS()
    wc.hInstance = hInstance
    wc.lpszClassName = className
    wc.lpfnWndProc = wndProc
    wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    wc.hbrBackground = 0
    try:
        atom = win32gui.RegisterClass(wc)
    except Exception as e:
        logging.error(f"Ошибка при регистрации класса окна: {e}")
        return

    screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    overlay_height = 45

    while True:
        try:
            # Добавлен флаг WS_EX_NOACTIVATE для предотвращения получения фокуса
            overlay_hwnd = win32gui.CreateWindowEx(
                win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE,
                className,
                "Overlay Window",
                win32con.WS_POPUP | win32con.WS_VISIBLE,
                0, screen_height - overlay_height,
                screen_width, overlay_height,
                0, 0, hInstance, None
            )

            win32gui.SetWindowPos(overlay_hwnd, win32con.HWND_TOPMOST,
                                  0, screen_height - overlay_height,
                                  screen_width, overlay_height, 0)
            # Запускаем поток для поддержания TopMost
            threading.Thread(target=maintain_topmost, args=(overlay_hwnd,), daemon=True).start()

            # Применяем прозрачность через DwmExtendFrameIntoClientArea
            dwmapi = ctypes.windll.dwmapi
            margins = MARGINS(-1, -1, -1, -1)
            result = dwmapi.DwmExtendFrameIntoClientArea(overlay_hwnd, byref(margins))
            if result != 0:
                logging.error(f"DwmExtendFrameIntoClientArea failed, error code: {result}")
            else:
                logging.info("DwmExtendFrameIntoClientArea succeeded")

            # Устанавливаем Display Affinity с проверкой версии Windows
            user32 = ctypes.windll.user32
            build_number = get_windows_build()
            affinity = WDA_EXCLUDEFROMCAPTURE if build_number >= 19041 else WDA_MONITOR
            result = user32.SetWindowDisplayAffinity(overlay_hwnd, affinity)
            if result == 0:
                logging.error("SetWindowDisplayAffinity failed")
            else:
                logging.info(f"SetWindowDisplayAffinity succeeded with {'WDA_EXCLUDEFROMCAPTURE' if build_number >= 19041 else 'WDA_MONITOR'}")

            win32gui.PumpMessages()
            break  # Если PumpMessages завершился нормально, выходим из цикла
        except Exception as e:
            logging.error(f"Ошибка оверлейного окна: {e}")
            time.sleep(1)  # Задержка перед повторной попыткой

def hide_console():
    """Скрывает консольное окно."""
    try:
        console_window = win32console.GetConsoleWindow()
        if console_window:
            win32gui.ShowWindow(console_window, win32con.SW_HIDE)
    except Exception as e:
        logging.error(f"Ошибка при скрытии консоли: {e}")

def main():
    threading.Thread(target=start_server, daemon=True).start()
    hide_console()  # Скрываем консоль сразу после запуска
    create_gui()
    if not current_id:
        print("ID не задан. Выход.")
        return
    main_overlay()

if __name__ == '__main__':
    main()