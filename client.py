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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tkinter as tk
import time
import platform
import json
import asyncio
import websockets

# Уровень логирования INFO для снижения нагрузки
logging.basicConfig(level=logging.INFO)

# Глобальные переменные
current_id = None
current_message = ""
overlay_hwnd = None
root = None

# Кэширование скриншотов
last_screenshot = None
last_capture_time = 0
SCREENSHOT_CACHE_DURATION = 1  # Кэшируем скриншот на 1 секунду

# Константы для Display Affinity
WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011

class MARGINS(Structure):
    _fields_ = [
        ("cxLeftWidth", c_int),
        ("cxRightWidth", c_int),
        ("cyTopHeight", c_int),
        ("cyBottomHeight", c_int)
    ]

########################################
# HTTP-сервер: обработчик запросов
########################################
class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global current_id, last_screenshot, last_capture_time
        if self.path.startswith('/screenshot/'):
            requested_id = self.path.split('/screenshot/')[1]
            if requested_id != current_id:
                logging.warning("Недействительный ID")
                self.send_response(403)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Invalid ID')
                return
            try:
                current_time = time.time()
                if current_time - last_capture_time > SCREENSHOT_CACHE_DURATION:
                    logging.info("Захватываем новый скриншот")
                    last_screenshot = pyautogui.screenshot()
                    last_capture_time = current_time
                else:
                    logging.info("Используем кэшированный скриншот")
                img_io = io.BytesIO()
                last_screenshot.save(img_io, 'PNG')  # Без сжатия
                img_io.seek(0)
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
            message = message.replace('\n', ' ')
            logging.info(f"Получено сообщение: {message}")
            current_message = message
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
    server = ThreadingHTTPServer(('0.0.0.0', 5000), RequestHandler)
    logging.info("HTTP-сервер запущен на 0.0.0.0:5000")
    server.serve_forever()

########################################
# Вспомогательные функции
########################################
def get_client_url():
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    return f'http://{local_ip}:5000'

BOT_REGISTRATION_URL = 'http://87.242.119.104:8000/register_client'

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

########################################
# WebSocket клиент для связи с ботом
########################################
async def ws_client():
    ws_url = "ws://87.242.119.104:8765"
    while True:
        try:
            async with websockets.connect(ws_url) as websocket:
                await websocket.send(json.dumps({"unique_id": current_id}))
                logging.info("WebSocket соединение установлено с сервером.")
                while True:
                    message = await websocket.recv()
                    try:
                        command = json.loads(message)
                        action = command.get("action")
                        if action == "screenshot":
                            logging.info("Получена команда на скриншот через WebSocket.")
                            screenshot = pyautogui.screenshot()
                            img_io = io.BytesIO()
                            screenshot.save(img_io, format="PNG")  # Без сжатия
                            img_bytes = img_io.getvalue()
                            await websocket.send(img_bytes)
                        elif action == "message":
                            text = command.get("text", "").replace('\n', ' ')
                            logging.info(f"Получено сообщение через WebSocket: {text}")
                            global current_message
                            current_message = text
                            if overlay_hwnd:
                                win32gui.RedrawWindow(overlay_hwnd, None, None, win32con.RDW_INVALIDATE | win32con.RDW_UPDATENOW)
                        elif action == "reset":
                            logging.info("Получен сброс через WebSocket.")
                            current_message = ""
                            if overlay_hwnd:
                                win32gui.RedrawWindow(overlay_hwnd, None, None, win32con.RDW_INVALIDATE | win32con.RDW_UPDATENOW)
                        else:
                            logging.warning(f"Неизвестная команда через WebSocket: {command}")
                    except Exception as e:
                        logging.error(f"Ошибка обработки сообщения WebSocket: {e}")
        except Exception as e:
            logging.error(f"Ошибка подключения WebSocket: {e}. Переподключение через 10 секунд...")
            await asyncio.sleep(10)

def start_ws_client_thread():
    asyncio.run(ws_client())

########################################
# Оконная процедура для оверлейного окна (Win32)
########################################
last_message = ""  # Для оптимизации рендеринга

def wndProc(hWnd, msg, wParam, lParam):
    global current_message, last_message
    if msg == win32con.WM_ERASEBKGND:
        return 1
    elif msg == win32con.WM_PAINT and current_message != last_message:
        last_message = current_message
        hdc, ps = win32gui.BeginPaint(hWnd)
        rect = win32gui.GetClientRect(hWnd)
        brush = win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0))
        win32gui.FillRect(hdc, rect, brush)
        win32gui.DeleteObject(brush)
        win32gui.SetTextColor(hdc, win32api.RGB(169, 169, 169))
        win32gui.SetBkMode(hdc, win32con.TRANSPARENT)

        font_size = 25
        hfont = ctypes.windll.gdi32.CreateFontW(
            font_size, 0, 0, 0, win32con.FW_NORMAL, False, False, False,
            win32con.ANSI_CHARSET, win32con.OUT_DEFAULT_PRECIS,
            win32con.CLIP_DEFAULT_PRECIS, win32con.DEFAULT_QUALITY,
            win32con.DEFAULT_PITCH | win32con.FF_DONTCARE, "Arial"
        )

        old_font = win32gui.SelectObject(hdc, hfont)
        flags = win32con.DT_CENTER | win32con.DT_WORDBREAK
        win32gui.DrawText(hdc, current_message, -1, rect, flags)
        win32gui.SelectObject(hdc, old_font)
        ctypes.windll.gdi32.DeleteObject(hfont)
        win32gui.EndPaint(hWnd, ps)
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
    while True:
        try:
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
            )
        except Exception as e:
            logging.error(f"Ошибка поддержания topmost: {e}")
        time.sleep(0.5)  # Увеличен интервал до 500 мс

########################################
# Функция создания оверлейного окна (Win32)
########################################
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
            extended_style = (win32con.WS_EX_TOOLWINDOW |
                              win32con.WS_EX_NOACTIVATE |
                              win32con.WS_EX_LAYERED |
                              win32con.WS_EX_TRANSPARENT)
            overlay_hwnd = win32gui.CreateWindowEx(
                extended_style,
                className,
                "Overlay Window",
                win32con.WS_POPUP | win32con.WS_VISIBLE,
                0, screen_height - overlay_height,
                screen_width, overlay_height,
                0, 0, hInstance, None
            )
            win32gui.SetLayeredWindowAttributes(overlay_hwnd, 0, 255, win32con.LWA_ALPHA)

            win32gui.SetWindowPos(overlay_hwnd, win32con.HWND_TOPMOST,
                                  0, screen_height - overlay_height,
                                  screen_width, overlay_height, 0)
            threading.Thread(target=maintain_topmost, args=(overlay_hwnd,), daemon=True).start()

            dwmapi = ctypes.windll.dwmapi
            margins = MARGINS(-1, -1, -1, -1)
            result = dwmapi.DwmExtendFrameIntoClientArea(overlay_hwnd, byref(margins))
            if result != 0:
                logging.error(f"DwmExtendFrameIntoClientArea failed, error code: {result}")
            else:
                logging.info("DwmExtendFrameIntoClientArea succeeded")

            user32 = ctypes.windll.user32
            build_number = get_windows_build()
            affinity = WDA_EXCLUDEFROMCAPTURE if build_number >= 19041 else WDA_MONITOR
            result = user32.SetWindowDisplayAffinity(overlay_hwnd, affinity)
            if result == 0:
                logging.error("SetWindowDisplayAffinity failed")
            else:
                logging.info(f"SetWindowDisplayAffinity succeeded with {'WDA_EXCLUDEFROMCAPTURE' if build_number >= 19041 else 'WDA_MONITOR'}")

            win32gui.PumpMessages()
            break
        except Exception as e:
            logging.error(f"Ошибка оверлейного окна: {e}")
            time.sleep(1)

def hide_console():
    try:
        console_window = win32console.GetConsoleWindow()
        if console_window:
            win32gui.ShowWindow(console_window, win32con.SW_HIDE)
    except Exception as e:
        logging.error(f"Ошибка при скрытии консоли: {e}")

def get_windows_build():
    version = platform.version()
    try:
        build = int(version.split('.')[-1])
        return build
    except (ValueError, IndexError):
        return 0

########################################
# Точка входа
########################################
def main():
    threading.Thread(target=start_server, daemon=True).start()
    hide_console()
    create_gui()
    if not current_id:
        print("ID не задан. Выход.")
        return
    threading.Thread(target=start_ws_client_thread, daemon=True).start()
    main_overlay()

if __name__ == '__main__':
    main()