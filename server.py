import tkinter as tk
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import pyautogui
import io
import logging

# Переменная для хранения уникального ID
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
                # Захватываем скриншот
                logging.debug("Захватываем скриншот")
                screenshot = pyautogui.screenshot()
                img_io = io.BytesIO()
                screenshot.save(img_io, 'PNG')
                img_io.seek(0)

                # Отправляем скриншот
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
            content_length = int(self.headers['Content-Length'])
            message = self.rfile.read(content_length).decode('utf-8')
            if message_label:
                message_label.config(text=message)
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Message received')

def start_server():
    """
    Запускает локальный HTTP-сервер для обработки запросов.
    """
    server = HTTPServer(('127.0.0.1', 5000), RequestHandler)
    logging.info("Сервер запущен на 127.0.0.1:5000")
    server.serve_forever()

def set_id():
    """
    Устанавливает уникальный ID из текстового поля.
    """
    global current_id
    current_id = id_entry.get()
    status_label.config(text=f"ID установлен: {current_id}")

def create_gui():
    """
    Создает простое GUI-приложение с вводом ID и отображением сообщений.
    """
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
    """
    Главная функция для запуска сервера и GUI.
    """
    server_thread = threading.Thread(target=start_server)
    server_thread.daemon = True
    server_thread.start()
    create_gui()

if __name__ == '__main__':
    main()