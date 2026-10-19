# -*- coding: utf-8 -*-
"""通用工具函数：路径、查询串解析、端口检测、开机自启、高 DPI。"""

import ctypes
import os
import random
import socket
import sys
import urllib.parse

from constants import AUTOSTART_KEY, AUTOSTART_NAME, CONFIG_FILE, IS_WINDOWS

if IS_WINDOWS:
    try:
        import winreg
    except ImportError:
        winreg = None
else:
    winreg = None


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------

def human_size(n):
    """把字节数格式化成可读字符串。"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d B" % int(n)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return "%.1f GB" % n


# ---------------------------------------------------------------------------
# 查询串解析（大小写不敏感）
# ---------------------------------------------------------------------------

def parse_qs_ci(query):
    """大小写不敏感的 query 解析。

    为什么需要：KVP 参数名大小写在实际客户端里并不统一，
    例如 ArcMap 发的是 `TileMatrix/TileRow/TileCol`（驼峰），
    而标准 WMTS 写的是 `TILEMATRIX/TILEROW/TILECOL`（全大写）。
    parse_qs 是**区分大小写**的，直接读全大写 key 会全部读空，
    导致瓦片请求被误判、缓存永远不生效。

    返回的字典：大写键 -> 值列表；另外在 "_raw" 里保留客户端
    原始的 (键, 值) 列表，便于向上游转发时保持原样。
    """
    raw = urllib.parse.parse_qs(query, keep_blank_values=True)
    out = {"_raw": []}
    for k, vals in raw.items():
        out.setdefault(k.upper(), []).extend(vals)
        for v in vals:
            out["_raw"].append((k, v))
    return out


def qget(qs, name, default=""):
    """从大小写不敏感的字典里取值（按大写 key 查）。"""
    v = qs.get(name.upper())
    return v[0] if v else default


def build_upstream_query(qs_ci, exclude=("TK",), extra=None):
    """把参数字典还原成上游 query 字符串。

    优先使用客户端原始的 key 大小写（存在 qs_ci["_raw"]），
    这样转发给天地图时不会被我们改写成别的形式。
    """
    exclude = {e.upper() for e in exclude}
    pairs = [(k, v) for k, v in (qs_ci.get("_raw") or [])
             if k.upper() not in exclude]
    if not pairs:
        pairs = [(k, vals[0]) for k, vals in qs_ci.items()
                 if k != "_raw" and k.upper() not in exclude]
    if extra:
        pairs.extend(extra)
    return urllib.parse.urlencode(pairs, doseq=True)


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

def app_base_dir():
    """程序所在目录（兼容 PyInstaller 单文件 exe）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def default_config_path():
    return os.path.join(app_base_dir(), CONFIG_FILE)


# ---------------------------------------------------------------------------
# 端口
# ---------------------------------------------------------------------------

def port_available(port):
    """检测端口能否被本程序占用。

    ⚠ Windows 的坑：SO_REUSEADDR 会「强行抢占」别的程序已绑定的端口
    （见 MSDN《Using SO_REUSEADDR and SO_EXCLUSIVEADDRUSE》：
      "allows a socket to forcibly bind to a port in use by another socket"），
    用它做占用检测会把「已被占用」误判成「可用」。因此这里：
      · Windows 用 SO_EXCLUSIVEADDRUSE —— 官方推荐，能真实反映端口占用；
      · 其它平台用 SO_REUSEADDR    —— 与服务器绑定行为一致，避免 TIME_WAIT 误判。
    另外先做一次 TCP 连接探测：能连上就说明确实有人在监听。
    """
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    if not 1 <= port <= 65535:
        return False

    # 1) 有没有程序在监听这个端口？（连得上就是被占用）
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.6)
    try:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return False
    except OSError:
        pass
    finally:
        probe.close()

    # 2) 能不能真正绑定？
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if IS_WINDOWS:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def find_free_port(candidates=(80, 8080, 8000, 8888, 9000, 12303, 12304, 10086)):
    """优先返回候选端口里可用的一个，都不行就随机找一个高位端口。"""
    for p in candidates:
        if port_available(p):
            return p
    for _ in range(30):
        p = random.randint(20000, 60000)
        if port_available(p):
            return p
    return None


# ---------------------------------------------------------------------------
# 开机自启（Windows 注册表 Run 项）
# ---------------------------------------------------------------------------

def _autostart_command():
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not script:
        script = os.path.join(app_base_dir(), "tianditu_gui.py")
    return '"%s" "%s"' % (sys.executable, script)


def autostart_supported():
    """当前平台是否支持开机自启设置。"""
    return winreg is not None


def set_autostart(enable):
    """设置/取消开机自启（写 HKCU Run 项）。返回 (成功, 说明)。"""
    if winreg is None:
        return False, "当前系统不支持开机自启设置"
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY)
        if enable:
            winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                winreg.DeleteValue(key, AUTOSTART_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True, ("已设置开机自启" if enable else "已取消开机自启")
    except Exception as e:
        return False, "设置失败：%s" % e


def get_autostart():
    """读取注册表判断是否已设置开机自启。"""
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, AUTOSTART_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 高 DPI
# ---------------------------------------------------------------------------

def enable_dpi_awareness():
    """Windows 高 DPI 下让界面不模糊（失败则忽略）。

    必须在创建 Tk 窗口之前调用。所有调用都做了保护——DPI 适配失败
    绝不能影响程序启动。
    """
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # PROCESS_SYSTEM_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
