import win32gui
import win32con
import win32api
import ctypes
import time

# Константы для Display Affinity
WDA_EXCLUDEFROMCAPTURE = 0x00000011  # Исключает окно из захвата (Windows 10 2004+)


# Оконная процедура
def wndProc(hWnd, msg, wParam, lParam):
    if msg == win32con.WM_ERASEBKGND:
        return 1  # Предотвращаем стандартную очистку фона
    elif msg == win32con.WM_PAINT:
        hdc, ps = win32gui.BeginPaint(hWnd)
        rect = win32gui.GetClientRect(hWnd)

        # Заполняем фон окна черным цветом (видимым для пользователя)
        brush = win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0))
        win32gui.FillRect(hdc, rect, brush)
        win32gui.DeleteObject(brush)

        # Настраиваем текст
        win32gui.SetTextColor(hdc, win32api.RGB(255, 255, 255))  # Белый текст
        win32gui.SetBkMode(hdc, win32con.TRANSPARENT)

        # Создаем шрифт
        font_size = 20
        hfont = ctypes.windll.gdi32.CreateFontW(
            font_size, 0, 0, 0, win32con.FW_NORMAL, False, False, False,
            win32con.ANSI_CHARSET, win32con.OUT_DEFAULT_PRECIS,
            win32con.CLIP_DEFAULT_PRECIS, win32con.DEFAULT_QUALITY,
            win32con.DEFAULT_PITCH | win32con.FF_DONTCARE, "Arial"
        )
        old_font = win32gui.SelectObject(hdc, hfont)

        # Рисуем текст
        text = "Hello, World!"
        flags = win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_SINGLELINE
        win32gui.DrawText(hdc, text, -1, rect, flags)

        # Очистка
        win32gui.SelectObject(hdc, old_font)
        ctypes.windll.gdi32.DeleteObject(hfont)
        win32gui.EndPaint(hWnd, ps)
        return 0
    elif msg == win32con.WM_DESTROY:
        win32gui.PostQuitMessage(0)
        return 0
    return win32gui.DefWindowProc(hWnd, msg, wParam, lParam)


# Основная функция создания окна
def create_overlay_window():
    hInstance = win32api.GetModuleHandle(None)
    className = "TransparentCaptureOverlay"

    # Регистрация класса окна
    wc = win32gui.WNDCLASS()
    wc.hInstance = hInstance
    wc.lpszClassName = className
    wc.lpfnWndProc = wndProc
    wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    wc.hbrBackground = 0
    win32gui.RegisterClass(wc)

    # Создание окна
    screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    width, height = 300, 100
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2

    hwnd = win32gui.CreateWindowEx(
        win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE,
        className,
        "Overlay Example",
        win32con.WS_POPUP | win32con.WS_VISIBLE,
        x, y, width, height,
        0, 0, hInstance, None
    )

    # Устанавливаем Display Affinity для исключения из захвата
    user32 = ctypes.windll.user32
    result = user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    if result == 0:
        print("Ошибка установки SetWindowDisplayAffinity")
    else:
        print("Успешно установлен WDA_EXCLUDEFROMCAPTURE")

    # Обновляем окно
    win32gui.UpdateWindow(hwnd)
    win32gui.PumpMessages()


if __name__ == "__main__":
    create_overlay_window()