import tkinter as tk
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import pyautogui
import io
import logging
import requests
import socket
import ctypes

logging.basicConfig(level=logging.DEBUG)

current_id = None
message_label = None
root = None  # Глобальное окно приложения


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

    def do_POST(self):
        if self.path == '/message':
            content_length = int(self.headers.get('Content-Length', 0))
            message = self.rfile.read(content_length).decode('utf-8')
            if message_label:
                message_label.config(text=message)
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Message received')


def start_server():
    server = HTTPServer(('0.0.0.0', 5000), RequestHandler)
    logging.info("Клиентский сервер запущен на 0.0.0.0:5000")
    server.serve_forever()


def get_client_url():
    """
    Определяет локальный IP-адрес устройства.
    Для продакшена рекомендуется использовать публичный IP или DDNS.
    """
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    return f'http://{local_ip}:5000'


# URL регистрации у бота (измените на реальный адрес бота, если требуется)
BOT_REGISTRATION_URL = 'http://127.0.0.1:8000/register_client'


def transform_to_overlay():
    """
    Преобразует интерфейс регистрации в минималистичный оверлей с прозрачным фоном,
    который закреплён поверх панели задач.
    """
    global root, message_label
    # Удаляем все существующие виджеты (регистрационная форма)
    for widget in root.winfo_children():
        widget.destroy()
    # Убираем рамку окна
    root.overrideredirect(True)
    # Окно всегда поверх остальных
    root.attributes("-topmost", True)
    # Задаём фон, который затем делаем прозрачным
    transparent_color = "magenta"
    root.config(bg=transparent_color)
    root.wm_attributes("-transparentcolor", transparent_color)

    # Создаем минимальный Label для отображения текста (без лишней информации)
    message_label = tk.Label(root, text="Сообщений нет", font=("Segoe UI", 12), bg=transparent_color, fg="white")
    message_label.pack(fill=tk.BOTH, expand=True)

    # Определяем размеры экрана и позиционируем окно внизу экрана (на тонкой линии панели задач)
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    new_width = screen_width
    new_height = 30  # минимальная высота
    x = 0
    y = screen_height - new_height  # располагаем в самом низу

    root.geometry(f"{new_width}x{new_height}+{x}+{y}")

    # Принудительно устанавливаем окно поверх панели задач через Windows API
    try:
        hwnd = root.winfo_id()
        HWND_TOPMOST = -1
        ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, new_width, new_height, 0)
    except Exception as e:
        logging.error("Ошибка установки окна над панелью задач: " + str(e))


def set_id():
    global current_id, root, status_label
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
            # После успешной регистрации преобразуем GUI в минимальный оверлей
            transform_to_overlay()
        else:
            status_label.config(text=f"Ошибка регистрации: {response.text}")
    except requests.exceptions.RequestException as e:
        status_label.config(text=f"Не удалось зарегистрироваться: {e}")


def create_gui():
    global root, id_entry, status_label, message_label
    root = tk.Tk()
    root.title("Helper Client")
    root.geometry("400x200")

    tk.Label(root, text="Введите уникальный ID:").pack(pady=5)
    id_entry = tk.Entry(root, width=40)
    id_entry.pack(pady=5)

    tk.Button(root, text="Подключиться", command=set_id).pack(pady=5)

    status_label = tk.Label(root, text="ID не установлен")
    status_label.pack(pady=5)

    # message_label будет создан в режиме overlay после регистрации
    root.mainloop()


def main():
    server_thread = threading.Thread(target=start_server)
    server_thread.daemon = True
    server_thread.start()
    create_gui()


if __name__ == '__main__':
    main()
