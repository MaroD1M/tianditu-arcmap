# -*- coding: utf-8 -*-
"""系统托盘（Windows，纯 ctypes，无第三方依赖）。"""

import ctypes
import os
import sys
import threading

from constants import IS_WINDOWS
from utils import app_base_dir


if IS_WINDOWS:
    def _safe_dll(name):
        """加载 DLL，并用安全代理包装。

        为什么需要：不同 Windows 版本导出的函数不完全一致（例如某些系统上
        TranslateMessageW 不是独立导出符号）。直接访问会抛 AttributeError，
        让程序**启动即崩溃**。托盘只是可选功能，绝不能因此打不开主界面。
        代理后：缺失的函数调用变成安全空操作，并把名字记进 _missing。
        """
        try:
            dll = ctypes.WinDLL(name, use_last_error=True)
        except Exception:
            try:
                dll = ctypes.WinDLL(name)
            except Exception:
                return _MissingDLL(name)

        class _Safe:
            def __init__(self, real, dll_name):
                object.__setattr__(self, "_real", real)
                object.__setattr__(self, "_name", dll_name)
                object.__setattr__(self, "_missing", set())
                object.__setattr__(self, "_cache", {})

            def __getattr__(self, item):
                real = object.__getattribute__(self, "_real")
                try:
                    return getattr(real, item)
                except AttributeError:
                    object.__getattribute__(self, "_missing").add(item)
                    cache = object.__getattribute__(self, "_cache")
                    if item not in cache:
                        cache[item] = _noop()
                    return cache[item]

        return _Safe(dll, name)

    class _MissingDLL:
        """整个 DLL 都加载不到时的替身。"""

        def __init__(self, name):
            object.__setattr__(self, "_name", name)
            object.__setattr__(self, "_cache", {})
            object.__setattr__(self, "_missing", set())

        def __getattr__(self, item):
            object.__getattribute__(self, "_missing").add(item)
            cache = object.__getattribute__(self, "_cache")
            if item not in cache:
                cache[item] = _noop()
            return cache[item]

    class _noop:
        """可被调用、可设置 restype/argtypes 的空操作。"""

        restype = None
        argtypes = None

        def __call__(self, *a, **k):
            return 0

    _user32 = _safe_dll("user32")
    _shell32 = _safe_dll("shell32")
    _kernel32 = _safe_dll("kernel32")

    # 供诊断使用：哪些 Win32 函数在本机不存在
    def win32_missing():
        names = set()
        for dll in (_user32, _shell32, _kernel32):
            try:
                names |= set(object.__getattribute__(dll, "_missing"))
            except Exception:
                pass
        return sorted(names)

    WM_USER = 0x0400
    WM_TRAYICON = WM_USER + 20
    WM_COMMAND = 0x0111
    WM_DESTROY = 0x0002
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205
    NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
    NIIF_INFO = 0x01
    MF_STRING, MF_SEPARATOR = 0x0000, 0x0800
    TPM_RETURNCMD, TPM_RIGHTBUTTON = 0x0100, 0x0002
    IDI_APPLICATION = 32512
    IMAGE_ICON = 1
    LR_LOADFROMFILE, LR_DEFAULTSIZE = 0x0010, 0x0040

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_uint,
                                 ctypes.c_size_t, ctypes.c_ssize_t)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", ctypes.c_uint),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", ctypes.c_void_p),
            ("hIcon", ctypes.c_void_p),
            ("hCursor", ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p),
            ("lpszMenuName", ctypes.c_wchar_p),
            ("lpszClassName", ctypes.c_wchar_p),
        ]

    class NOTIFYICONDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("hWnd", ctypes.c_void_p),
            ("uID", ctypes.c_uint),
            ("uFlags", ctypes.c_uint),
            ("uCallbackMessage", ctypes.c_uint),
            ("hIcon", ctypes.c_void_p),
            ("szTip", ctypes.c_wchar * 128),
            ("dwState", ctypes.c_uint),
            ("dwStateMask", ctypes.c_uint),
            ("szInfo", ctypes.c_wchar * 256),
            ("uTimeout", ctypes.c_uint),
            ("szInfoTitle", ctypes.c_wchar * 64),
            ("dwInfoFlags", ctypes.c_uint),
        ]

    # 关键：显式声明返回类型，否则 ctypes 默认按 c_int(32位) 返回，
    # 64 位下句柄会被截断成垃圾值，导致托盘图标加载失败、图标不显示。
    #
    # 注意：这里全部用 _declare() 包裹。原因：
    #   1) 某些 Windows 上并非所有 W 后缀函数都被导出（例如 TranslateMessageW），
    #      直接访问属性会抛 AttributeError，导致程序**启动即崩溃**；
    #   2) 托盘只是可选功能，绝不能因为它让主程序打不开。
    def _declare(func, restype=None, argtypes=None):
        try:
            if restype is not None:
                func.restype = restype
            if argtypes is not None:
                func.argtypes = argtypes
            return func
        except AttributeError:
            return None          # 该函数在这台机器上不存在，忽略

    _declare(_user32.DefWindowProcW, LRESULT,
             [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t])
    _declare(_user32.CreateWindowExW, ctypes.c_void_p,
             [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint,
              ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
              ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p])
    _declare(_user32.LoadIconW, ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p])
    _declare(_user32.LoadImageW, ctypes.c_void_p,
             [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
              ctypes.c_int, ctypes.c_int, ctypes.c_uint])
    _declare(_user32.CreatePopupMenu, ctypes.c_void_p)
    _declare(_user32.GetCursorPos, None, [ctypes.c_void_p])
    _declare(_user32.SetForegroundWindow, None, [ctypes.c_void_p])
    _declare(_user32.DestroyMenu, None, [ctypes.c_void_p])
    _declare(_user32.DestroyWindow, None, [ctypes.c_void_p])
    _declare(_user32.PostMessageW, None,
             [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t])
    _declare(_user32.RegisterClassW, None, [ctypes.c_void_p])
    _declare(_user32.TrackPopupMenu, ctypes.c_int)
    _declare(_user32.GetMessageW, None,
             [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint])
    _declare(_user32.DispatchMessageW, None, [ctypes.c_void_p])
    # TranslateMessageW 在个别系统上不是独立导出符号，声明失败也不影响托盘功能
    _declare(_user32.TranslateMessageW, None, [ctypes.c_void_p])
    _declare(_user32.PostQuitMessage, None, [ctypes.c_int])

    _declare(_shell32.Shell_NotifyIconW, ctypes.c_int,
             [ctypes.c_uint, ctypes.c_void_p])
    _declare(_shell32.ExtractIconW, ctypes.c_void_p,
             [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint])
    _declare(_kernel32.GetModuleHandleW, ctypes.c_void_p, [ctypes.c_wchar_p])
    _declare(_kernel32.GetLastError, ctypes.c_uint)


class TrayIcon:
    """Windows 系统托盘图标（ctypes 调用 Shell_NotifyIcon）。

    托盘消息在独立线程的消息循环里处理，动作通过回调 push 到队列，
    由主线程（Tk）消费，避免跨线程操作界面。
    """

    MENU = [("show", "显示主界面"), ("start", "启动服务"),
            ("stop", "停止服务"), (None, None), ("quit", "退出")]

    def __init__(self, tooltip, callback):
        self.tooltip = tooltip
        self.callback = callback          # callback(action:str)
        self.available = IS_WINDOWS
        self.error = "" if IS_WINDOWS else "当前系统不是 Windows"
        self._hwnd = None
        self._nid = None
        self._thread = None
        self._wndproc_ref = None
        self._class_name = "TiandituTray_%d" % id(self)
        self._ready = threading.Event()

    # ---- 对外接口 ----------------------------------------------------------
    def start(self):
        if not self.available or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            self.available = False
            self.error = "托盘线程初始化超时"

    def stop(self, wait=2.0):
        """停止托盘：移除图标 + 结束消息循环 + 等待线程退出。

        ⚠ 只发 WM_DESTROY 不等线程结束是不够的：主线程会继续 destroy()
        并让 mainloop 返回，进程可能在托盘线程还活着时就开始退出，
        表现为「图标没了但进程残留」。
        """
        hwnd = self._hwnd
        if hwnd:
            try:
                _user32.PostMessageW(ctypes.c_void_p(hwnd), WM_DESTROY, 0, 0)
            except Exception:
                pass
        # 等托盘线程真正结束
        t = self._thread
        if t is not None and t.is_alive():
            try:
                t.join(timeout=wait)
            except Exception:
                pass
        # 兜底：线程仍活着就强制移除图标
        if self._nid is not None:
            try:
                _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            except Exception:
                pass
            self._nid = None
        self._hwnd = None
        return not (t is not None and t.is_alive())

    def notify(self, title, msg):
        if not self._nid:
            return
        try:
            self._nid.uFlags = NIF_INFO
            self._nid.szInfoTitle = title[:63]
            self._nid.szInfo = msg[:255]
            self._nid.dwInfoFlags = NIIF_INFO
            self._nid.uTimeout = 5000
            _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))
        except Exception:
            pass

    # ---- 失败上报（带 Win32 错误码，方便定位）-----------------------------
    @staticmethod
    def _last_error():
        try:
            return _kernel32.GetLastError()
        except Exception:
            return 0

    def _fail(self, what, detail=""):
        code = self._last_error()
        self.available = False
        extra = ""
        try:
            miss = win32_missing()
            if miss:
                extra = "；本机缺少 Win32 函数：%s" % ", ".join(miss[:6])
        except Exception:
            pass
        self.error = "%s（Win32 错误码 %d）%s%s" % (
            what, code, ("：" + detail) if detail else "", extra)
        self._ready.set()

    # ---- 内部实现 ----------------------------------------------------------
    def _load_icon(self):
        # 优先用 exe 自带图标，其次外部 icon.ico，最后系统默认图标
        try:
            if getattr(sys, "frozen", False):
                h = _shell32.ExtractIconW(None, sys.executable, 0)
                if h and h != 1:
                    return h
        except Exception:
            pass
        ico = os.path.join(app_base_dir(), "icon.ico")
        if os.path.exists(ico):
            h = _user32.LoadImageW(None, ico, IMAGE_ICON, 0, 0,
                                   LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                return h
        return _user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            event = lparam & 0xFFFF
            if event == WM_LBUTTONDBLCLK:
                self.callback("show")
            elif event == WM_RBUTTONUP:
                self._show_menu(hwnd)
            return 0
        if msg == WM_COMMAND:
            cmd = wparam & 0xFFFF
            for idx, (action, _label) in enumerate(self.MENU, start=1):
                if action and cmd == idx:
                    self.callback(action)
                    break
            return 0
        if msg == WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(ctypes.c_void_p(hwnd), msg, wparam, lparam)

    def _show_menu(self, hwnd):
        menu = _user32.CreatePopupMenu()
        for idx, (action, label) in enumerate(self.MENU, start=1):
            if action is None:
                _user32.AppendMenuW(ctypes.c_void_p(menu), MF_SEPARATOR, 0, None)
            else:
                _user32.AppendMenuW(ctypes.c_void_p(menu), MF_STRING, idx, label)
        _user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        pt = POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        cmd = _user32.TrackPopupMenu(ctypes.c_void_p(menu),
                                     TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                     pt.x, pt.y, 0, ctypes.c_void_p(hwnd), None)
        _user32.DestroyMenu(ctypes.c_void_p(menu))
        if cmd:
            _user32.PostMessageW(ctypes.c_void_p(hwnd), WM_COMMAND, cmd, 0)

    def _run(self):
        try:
            hinst = _kernel32.GetModuleHandleW(None)
            self._wndproc_ref = WNDPROC(self._wndproc)

            wc = WNDCLASS()
            wc.lpfnWndProc = self._wndproc_ref
            wc.hInstance = hinst
            wc.lpszClassName = self._class_name
            if not _user32.RegisterClassW(ctypes.byref(wc)):
                # 类名重复不算致命，CreateWindowExW 仍可能成功
                self._reg_error = self._last_error()
            else:
                self._reg_error = 0

            hwnd = _user32.CreateWindowExW(0, self._class_name, self._class_name,
                                           0, 0, 0, 0, 0, None, None,
                                           ctypes.c_void_p(hinst), None)
            if not hwnd:
                self._fail("创建隐藏窗口失败(CreateWindowExW)",
                           "RegisterClass 错误码=%s" % getattr(self, "_reg_error", "?"))
                return
            self._hwnd = hwnd

            nid = NOTIFYICONDATA()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
            nid.hWnd = hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAYICON
            nid.hIcon = self._load_icon()
            nid.szTip = self.tooltip[:127]
            if not nid.hIcon:
                self._fail("加载托盘图标失败")
                return
            if not _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                self._fail("添加托盘图标失败(Shell_NotifyIcon NIM_ADD)")
                return
            self._nid = nid
            self._ready.set()

            msg = MSG()
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                # TranslateMessage 只影响键盘加速键，托盘用不到；
                # 某些系统上它不是独立导出符号，失败就跳过。
                try:
                    _user32.TranslateMessageW(ctypes.byref(msg))
                except Exception:
                    pass
                _user32.DispatchMessageW(ctypes.byref(msg))

            _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            _user32.DestroyWindow(ctypes.c_void_p(hwnd))
            self._hwnd = None
            self._nid = None
        except Exception as e:
            self.available = False
            self.error = "托盘初始化异常：%r" % (e,)
            self._ready.set()


if IS_WINDOWS:
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                    ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                    ("time", ctypes.c_uint), ("pt", POINT)]
