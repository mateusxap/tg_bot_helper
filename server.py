import tkinter as tk
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import pyautogui
import io
import logging
import requests
import socket

logging.basicConfig(level=logging.DEBUG)

current_id = None
message_label = None

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
        else:
            status_label.config(text=f"Ошибка регистрации: {response.text}")
    except requests.exceptions.RequestException as e:
        status_label.config(text=f"Не удалось зарегистрироваться: {e}")

def create_gui():
    global id_entry, status_label, message_label
    root = tk.Tk()
    root.title("Helper Client")
    root.geometry("400x200")

    tk.Label(root, text="Введите уникальный ID:").pack(pady=5)
    id_entry = tk.Entry(root, width=40)
    id_entry.pack(pady=5)

    tk.Button(root, text="Подключиться", command=set_id).pack(pady=5)

    status_label = tk.Label(root, text="ID не установлен")
    status_label.pack(pady=5)

    message_label = tk.Label(root, text="Сообщений нет", wraplength=350)
    message_label.pack(pady=10)

    root.mainloop()

def main():
    server_thread = threading.Thread(target=start_server)
    server_thread.daemon = True
    server_thread.start()
    create_gui()

if __name__ == '__main__':
    main()
