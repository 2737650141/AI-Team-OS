"""Native Win32 accessibility fixture for manual M5-A integration acceptance."""

from __future__ import annotations

import win32api  # type: ignore[import-untyped]
import win32con  # type: ignore[import-untyped]
import win32gui  # type: ignore[import-untyped]

TITLE = "AI Team OS Windows UI Automation Test Fixture"
STATUS_ID = 201


def window_proc(hwnd, message, wparam, lparam):
    if message == win32con.WM_COMMAND:
        control_id = win32api.LOWORD(wparam)
        status = win32gui.GetDlgItem(hwnd, STATUS_ID)
        if control_id == 101:
            win32gui.SetWindowText(status, "Button clicked")
        elif control_id == 105:
            win32gui.SetWindowText(status, "ELEVATION_REQUIRED")
        elif control_id == 107:
            win32gui.MessageBox(hwnd, "Fixture dialog", "Fixture Dialog", win32con.MB_OK)
        return 0
    if message == win32con.WM_DESTROY:
        win32gui.PostQuitMessage(0)
        return 0
    return win32gui.DefWindowProc(hwnd, message, wparam, lparam)


def child(
    parent: int,
    class_name: str,
    text: str,
    control_id: int,
    x: int,
    y: int,
    width: int,
    height: int,
    style: int = 0,
) -> int:
    return win32gui.CreateWindowEx(
        0,
        class_name,
        text,
        win32con.WS_CHILD | win32con.WS_VISIBLE | style,
        x,
        y,
        width,
        height,
        parent,
        control_id,
        win32api.GetModuleHandle(None),
        None,
    )


def main() -> None:
    module = win32api.GetModuleHandle(None)
    class_name = "AI_TEAM_OS_M5A_FIXTURE"
    window_class = win32gui.WNDCLASS()
    window_class.hInstance = module
    window_class.lpszClassName = class_name
    window_class.lpfnWndProc = window_proc
    window_class.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    window_class.hbrBackground = win32con.COLOR_WINDOW + 1
    try:
        win32gui.RegisterClass(window_class)
    except win32gui.error:
        pass

    hwnd = win32gui.CreateWindowEx(
        0,
        class_name,
        TITLE,
        win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
        180,
        140,
        660,
        520,
        0,
        0,
        module,
        None,
    )
    child(hwnd, "STATIC", "M5-A Accessibility Fixture", 200, 28, 24, 340, 24)
    child(hwnd, "BUTTON", "Fixture Action", 101, 28, 64, 180, 32, win32con.BS_PUSHBUTTON)
    child(hwnd, "STATIC", "Text", 210, 28, 112, 90, 22)
    child(
        hwnd,
        "EDIT",
        "",
        102,
        124,
        106,
        430,
        28,
        win32con.WS_BORDER | win32con.ES_AUTOHSCROLL,
    )
    child(hwnd, "STATIC", "Password", 211, 28, 154, 90, 22)
    child(
        hwnd,
        "EDIT",
        "",
        103,
        124,
        148,
        430,
        28,
        win32con.WS_BORDER | win32con.ES_PASSWORD | win32con.ES_AUTOHSCROLL,
    )
    child(
        hwnd,
        "BUTTON",
        "Fixture Checkbox",
        104,
        28,
        196,
        210,
        28,
        win32con.BS_AUTOCHECKBOX,
    )
    combo = child(
        hwnd,
        "COMBOBOX",
        "",
        106,
        270,
        194,
        220,
        140,
        win32con.CBS_DROPDOWNLIST | win32con.WS_VSCROLL,
    )
    for value in ("Alpha", "Beta", "Gamma"):
        win32gui.SendMessage(combo, win32con.CB_ADDSTRING, 0, value)
    win32gui.SendMessage(combo, win32con.CB_SETCURSEL, 0, 0)
    child(hwnd, "STATIC", "List", 212, 270, 238, 90, 22)
    list_box = child(
        hwnd,
        "LISTBOX",
        "",
        108,
        364,
        232,
        190,
        76,
        win32con.LBS_STANDARD,
    )
    for value in ("One", "Two", "Three"):
        win32gui.SendMessage(list_box, win32con.LB_ADDSTRING, 0, value)
    win32gui.SendMessage(list_box, win32con.LB_SETCURSEL, 0, 0)
    child(hwnd, "BUTTON", "Simulate UAC", 105, 28, 330, 180, 32, win32con.BS_PUSHBUTTON)
    child(hwnd, "BUTTON", "Open Dialog", 107, 228, 330, 180, 32, win32con.BS_PUSHBUTTON)
    child(hwnd, "STATIC", "Ready", STATUS_ID, 28, 384, 520, 28, win32con.SS_LEFT)
    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    win32gui.UpdateWindow(hwnd)
    win32gui.PumpMessages()


if __name__ == "__main__":
    main()
