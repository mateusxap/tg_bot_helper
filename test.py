import win32gui
import win32con
import win32api
import ctypes
from ctypes import Structure, byref, c_int

# Константы для Display Affinity
WDA_NONE = 0
WDA_MONITOR = 1

# Определяем структуру MARGINS для DwmExtendFrameIntoClientArea
class MARGINS(Structure):
    _fields_ = [
        ("cxLeftWidth", c_int),
        ("cxRightWidth", c_int),
        ("cyTopHeight", c_int),
        ("cyBottomHeight", c_int)
    ]

def wndProc(hWnd, msg, wParam, lParam):
    if msg == win32con.WM_PAINT:
        # Начинаем перерисовку окна
        hdc, ps = win32gui.BeginPaint(hWnd)
        rect = win32gui.GetClientRect(hWnd)
        # Не заполняем фон – пусть остаётся прозрачным (эффект стекла от DWM)
        win32gui.SetTextColor(hdc, 0xFFFFFF)  # Белый текст
        win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
        flags = win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_SINGLELINE
        text = "Overlay Text"
        win32gui.DrawText(hdc, text, -1, rect, flags)
        win32gui.EndPaint(hWnd, ps)
        return 0
    elif msg == win32con.WM_DESTROY:
        win32gui.PostQuitMessage(0)
        return 0
    else:
        return win32gui.DefWindowProc(hWnd, msg, wParam, lParam)

def main():
    hInstance = win32api.GetModuleHandle(None)
    className = "MyNativeOverlayWindowClass"

    # Регистрируем класс окна; для прозрачности не задаём фон (hbrBackground = 0)
    wc = win32gui.WNDCLASS()
    wc.hInstance = hInstance
    wc.lpszClassName = className
    wc.lpfnWndProc = wndProc
    wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    wc.hbrBackground = 0  # Нет кисти, чтобы не перерисовывать фон
    atom = win32gui.RegisterClass(wc)
    if not atom:
        print("Не удалось зарегистрировать класс окна")
        return

    # Получаем размеры экрана
    screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    overlay_height = 30

    # Создаём окно без рамки (WS_POPUP) и сразу показываем его (WS_VISIBLE)
    hwnd = win32gui.CreateWindowEx(
        0,
        className,
        "Overlay Window",
        win32con.WS_POPUP | win32con.WS_VISIBLE,
        0, screen_height - overlay_height,
        screen_width, overlay_height,
        0, 0, hInstance, None
    )

    # Устанавливаем окно всегда поверх (HWND_TOPMOST)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST,
                          0, screen_height - overlay_height,
                          screen_width, overlay_height, 0)

    # Пытаемся "протянуть" эффект стекла на клиентскую область через DwmExtendFrameIntoClientArea
    dwmapi = ctypes.windll.dwmapi
    margins = MARGINS(-1, -1, -1, -1)
    result = dwmapi.DwmExtendFrameIntoClientArea(hwnd, byref(margins))
    if result != 0:
        print("DwmExtendFrameIntoClientArea failed, error code:", result)
    else:
        print("DwmExtendFrameIntoClientArea succeeded")

    # Устанавливаем Display Affinity через ctypes
    user32 = ctypes.windll.user32
    result = user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR)
    if result == 0:
        print("Не удалось установить Display Affinity для окна.")
    else:
        print("Display Affinity успешно установлена.")

    # Запускаем цикл обработки сообщений
    win32gui.PumpMessages()

if __name__ == '__main__':
    main()
