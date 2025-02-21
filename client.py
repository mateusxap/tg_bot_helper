import win32gui
import win32con
import win32api
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

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)

# Глобальные переменные
current_id = None         # введённый ID
current_message = "Сообщений нет"  # текст, который будет отображаться в оверлее
overlay_hwnd = None       # дескриптор оверлейного окна
root = None               # окно Tkinter для ввода ID

# Константы для Display Affinity
WDA_NONE = 0
WDA_MONITOR = 1

# Структура для DwmExtendFrameIntoClientArea (эффект стекла)
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
                # Полная перерисовка окна для предотвращения наложения текста
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

########################################
# Вспомогательные функции
########################################
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
                root.destroy()  # Закрываем окно ввода после успешной регистрации
            else:
                status_label.config(text=f"Ошибка регистрации: {response.text}")
        except requests.exceptions.RequestException as e:
            status_label.config(text=f"Не удалось зарегистрироваться: {e}")

    tk.Button(root, text="Подключиться", command=set_id).pack(pady=5)
    root.mainloop()

########################################
# Оконная процедура для оверлейного окна (Win32)
########################################
def wndProc(hWnd, msg, wParam, lParam):
    global current_message
    if msg == win32con.WM_ERASEBKGND:
        # Возвращаем 1, чтобы предотвратить стандартную очистку фона и избежать наложения текста
        return 1
    elif msg == win32con.WM_PAINT:
        hdc, ps = win32gui.BeginPaint(hWnd)
        rect = win32gui.GetClientRect(hWnd)
        # Заполняем фон сплошным цветом для очистки предыдущего содержимого
        brush = win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0))
        win32gui.FillRect(hdc, rect, brush)
        win32gui.DeleteObject(brush)
        win32gui.SetTextColor(hdc, win32api.RGB(255, 255, 255))  # белый текст
        win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
        flags = win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_SINGLELINE
        win32gui.DrawText(hdc, current_message, -1, rect, flags)
        win32gui.EndPaint(hWnd, ps)
        return 0
    elif msg == win32con.WM_DESTROY:
        win32gui.PostQuitMessage(0)
        return 0
    else:
        return win32gui.DefWindowProc(hWnd, msg, wParam, lParam)

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
    # Фон не задаём – очистка будет выполняться вручную
    wc.hbrBackground = 0
    try:
        atom = win32gui.RegisterClass(wc)
    except Exception as e:
        logging.error(f"Ошибка при регистрации класса окна: {e}")
        return

    screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    overlay_height = 12

    # Основной цикл для восстановления оверлейного окна в случае ошибки
    while True:
        try:
            overlay_hwnd = win32gui.CreateWindowEx(
                win32con.WS_EX_APPWINDOW,  # окно будет отображаться в Alt+Tab и на панели задач
                className,
                "Overlay Window",
                win32con.WS_POPUP | win32con.WS_VISIBLE,
                0, screen_height - overlay_height,
                screen_width, overlay_height,
                0, 0, hInstance, None)

            win32gui.SetWindowPos(overlay_hwnd, win32con.HWND_TOPMOST,
                                  0, screen_height - overlay_height,
                                  screen_width, overlay_height, 0)

            # Применяем прозрачность через DwmExtendFrameIntoClientArea
            dwmapi = ctypes.windll.dwmapi
            margins = MARGINS(-1, -1, -1, -1)
            result = dwmapi.DwmExtendFrameIntoClientArea(overlay_hwnd, byref(margins))
            if result != 0:
                logging.error(f"DwmExtendFrameIntoClientArea failed, error code: {result}")
            else:
                logging.info("DwmExtendFrameIntoClientArea succeeded")

            # Устанавливаем Display Affinity
            user32 = ctypes.windll.user32
            result = user32.SetWindowDisplayAffinity(overlay_hwnd, WDA_MONITOR)
            if result == 0:
                logging.error("SetWindowDisplayAffinity failed")
            else:
                logging.info("SetWindowDisplayAffinity succeeded")

            win32gui.PumpMessages()
            break  # Если PumpMessages завершился нормально, выходим из цикла
        except Exception as e:
            logging.error(f"Ошибка оверлейного окна: {e}")
            time.sleep(1)  # Задержка перед попыткой восстановления окна

########################################
# Основная функция
########################################
def main():
    # Запускаем HTTP-сервер в отдельном потоке
    threading.Thread(target=start_server, daemon=True).start()

    # Запускаем окно для ввода ID (Tkinter)
    create_gui()

    if not current_id:
        print("ID не задан. Выход.")
        return

    # После ввода ID запускаем оверлейное окно
    main_overlay()

if __name__ == '__main__':
    main()