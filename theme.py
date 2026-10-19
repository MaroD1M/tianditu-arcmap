# -*- coding: utf-8 -*-
"""界面主题：统一的现代配色与控件样式。

本模块只依赖 tkinter（运行期依然零第三方依赖）。
gui 在启动时调用 `apply(root)` 应用主题，并用 `checkbutton()` 创建复选框
（自带显示「√」的指示器，避免各平台主题把勾选框画成「×」）。
"""

import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------- 配色
# 浅色底 + 鲜明强调色，避免灰暗、单调的观感。
BG         = "#f3f5f9"   # 窗口 / 页签外背景
CARD       = "#ffffff"   # 卡片 / 页签内背景
BORDER     = "#dbe3ee"   # 边框
TEXT       = "#1f2937"   # 正文
MUTED      = "#6b7280"   # 次要文字
PRIMARY    = "#2563eb"   # 主强调色
PRIMARY_D  = "#1d4ed8"   # 主强调色（按下 / 悬停）
PRIMARY_S  = "#e8f0fe"   # 主强调色（浅色底）
SUCCESS    = "#16a34a"   # 运行中 / 启动
SUCCESS_D  = "#15803d"
DANGER     = "#dc2626"   # 停止 / 危险操作
DANGER_D   = "#b91c1c"
HEAD_BG    = "#eef2f8"   # 表头
HEAD_FG    = "#334155"
ROW_ALT    = "#e9eef6"   # 隔行底色（比白底明显一档，强化行分隔）
SEL_BG     = "#dbeafe"   # 单元格选中底色
CELL_LINE  = "#d5deea"   # 单元格 / 列分隔线
HEADER_TX  = "#ffffff"   # 顶栏文字
HEADER_SUB = "#d7e4ff"   # 顶栏次要文字

FONT = "Microsoft YaHei UI"
MONO = ("Consolas", 10)

# 复选框指示器图片（PNG，base64）。右侧自带间距，无需依赖主题 padding。
_ICON_ON_18 = ("iVBORw0KGgoAAAANSUhEUgAAABkAAAASCAYAAACuLnWgAAADMElEQVR4nLWVS2icVRTHf+fe75uZzCuJTVuISikuVLBFM22pWKiLIFbEbHQlVCw1vopIEXdSKyJZCIKPIqGWUsSF4EJBkBLwQbLLKBaqggqW2pqKMfP45vl99x4X00JSJ2O68MLhbs7//M/5H+7/CgDH1HBcPCC3Tl3Yh+8+oJqEqGfNEYNIEGNSZy9+um0e0FXYdY9cSxp/5Pw9gWTfxuh9Np0VkL4AVUXipgpmoZ1UXrj82d3f/ReRAHLL1K93ico3YaE4YlKJirXrAoyBepSYbiuQIVerWJfc/9vnt38/iMiUphcDdZ2TYWF4xGZ8LDYQFHt9qGKtYKOG2smJrDw1lY4lOzySmORUaXoxHCSXubI0dK8NMntMKvEgIap9EwMDUVu5bdzy/pECbzxRCCfuFNfx+YmomtvNcfE8prYvCYl50GayKtb0rw6IQOwglxHeebbIUFr46lyXny55zRdz2mroJAB/9l+kUZztlQEjYE3vXpMkUGt6Xj+YZ+f2gB8vJhw5UaPVASMiTtUMlEtE9Fq3jY5SbSitrmINKBBYWK4rTx/I8ui+DFFLOTpbZyVSsmnw686/Wq6rnTY7cKCU5uSLRXZuD1mJlEwIlYayf0fIscfzqMJrH0WUf4kZyQnJwNexmkSuap4oByczPLQ7zZmXiuy9I+SPvz3bNlvee65IYOH0XItTZ1uMFQ2x2xhBj0R7I6dDYebjBit1ZTRvOPF8kZvHLDOH8mwZMcyfj3nlTMRY0eBugADAqKqoQjYNiz/HPPlWlWZHGd9k+HJmlP07UizXPEdna4S2ZwQbWMNaEsE6UE08bCoYFn7o8uqHEQA3FQzOwzPv1ri07MmkwP9rD6oig73LEPgvXLspOC+xg83DhtNzLV7+IOL3vzxvftLg63NdhnOCu66Uei++0xBvZQ6ALf2HlNL0Yrh0OTufHt66x2ZcjJjQoNRbymheaLSVVCBr0SKgPnZtE3YrV77dutTaW3645Nb1rvLsrkRs+nBcr1Zc24TqEvXgCjlx7QSXSolTwbEq1CXq2iaM69VKQHCoXN4VD5Lrhq0eFNdpKl4WEq1u2Or/90/rH+zAkp4BKFmMAAAAAElFTkSuQmCC")
_ICON_OFF_18 = ("iVBORw0KGgoAAAANSUhEUgAAABkAAAASCAYAAACuLnWgAAAB+0lEQVR4nN1Vv2tTURT+zrl599Wmhi4KBe2g0oJ2UbCocXCQ4JC1/Qd07iqi+HigiINLt0BHp3bNIMFJGgWFiohCizq0UlGXGhvjuy/3HIcQ6JD3aEA7+MEHZ/jO/c4POJcAIIqU45gEAN1fXLnspVtRkUAg2AsGg5hTw4XG7YW5VQC6JzcTFEURx3EsNx8snS2OFheTJCkrmHKTIBqGYbP9o73w8O6N1/03svUA3Xn0eCYw/Mx7HS8VrU6fmpTQBhBVEHp+CgUTIXEp1j9scqvtyBjaSTudK/duXX+T1xHVarXgc2tklTiYnZk6llYrlwJrDbJaUQDOedQbz9O3G1sBJF37WkouTGxv+6xu+FureFEUs6UxK9VKOQCA9i+XSwCoVsrB+NiIB5lzEz8PnY/jWOaWl81Ak67RawrS6ZOTai2j2/UwzOAMGu5prGVMnTiuClYQXQWA0++ODBwAq4oBQKENMkc0cM4AbBj0Q87TMhErAKjqEBY97Dcnt4K/hf/IRFUIAIiGWXsP+81hIvYANHEphlm9AnBJ2g9zbxcXPD0hKK1/3CTnBIWCgReBZNBLT+OcYOPTFhGEoPoUAN6f+T6wTj5aar9gwsvWruN6o5kCQHHU5hIA6o1murP720D92pfDnVdRFPHK/LwfZHIwB/KgTv0//7T+ACY9Sy1QGF5TAAAAAElFTkSuQmCC")
_ICON_ON_24 = ("iVBORw0KGgoAAAANSUhEUgAAACEAAAAYCAYAAAB0kZQKAAAEZElEQVR4nM2Wa4hVVRTHf2uffe/cx9w7U6N+yByll6MhhBBkFIVJfciMoBGp0ITsU48ZQgKtxiAJCnEi6EWBA72c24NE/CSShhpIEAbZVFQ6Q0RZNnOfc+/ee/XhOsNM87pTH2rBORzOgf/+nfVfe68lTIxOjciJB1h2389LfamyHO+UyAnThbdKZCVKJQZ+eveys3/XaDQmiKuAaPs936/VINvRsEbEtGgDAqphGDEnxeiL5z6+6siY1jwgBDr3R+Q2+vYNA3uJEl0m1oSxDonmFlJAvArB4qujOFfpHTqwvJvO/ohcZ2gERsbS177+zF6TXNQltuCjVBJjjFFlehsmhBFwAR0u+BB3ZRI2E1WLv/QOHby2u1FrBGDJ3QM3i0keixJSizUnrQadc/ExgEpNWZA1bF6X5Mjpmp74YsSlDTFXLdw6dHDl0UZADD09RkN4xsTiRKkm0yiACAStg7zxeAuPbUixrzsrqzrSpqoWY9gFPYaVzGmHWfrlpnaQNSZyKmJMIwAAkYELhUDP/c2svtJSqSqtaWFBizUep0h0wxXrOy/nWQmgs+oab6RDTCwtVoC5awDARvD7SGDTLQm2rEsyWlMSceHlAyWOnh6VbDZSTCLhosTVAHTOrmtEQ5jy0tTTPFMGihVlRbtl95YMLkBTTDhxpsYLHxRpaTaMKYrqFO1pIaYDKJSVclWJpkliUAgBnt+aIZsShHpWul4bwZp6rcw3Ji0jQL6k3LgixjWLLfnyZBAbwR/5wJMb06zpiFF19e9PvJln8LdAMi5Mzes8IIyB0qjywNok/Tta+XBnK6uWWYqV+kI2ggsF5c7rm3jkrhRVp8St0He4zKFTo1ySEdw/ABiHGMtgCLD5tgQA2bSw9+HM+FasVGFxm2HPtgxBIW6F0z86dr1ToDVt8P8QYBxCL95iFp7qKzBcVJxXOpZY9mzLkC8rpVFl94MZ2rIGH5ThovLoqyP4UC9WbbhTTA079hAUkgnh+NdVHnppmNyOVpxX7r0pQb6kDJ733LE6Pm5Dz9t5zgw6FmYNtXn1zFkgAHyAhS2GY1/V2NlXYPeWZpyHrbcnAXC+bsNHx0fZf6xCW+bfAwBYFWMm9rmah7as8PqhEiLw3OZmqq6+9WwEA0OeHfvypJuEMIcFKtLQCWyioN9oqBXVjVVG/Y8XtRpeOVhi3+EycQuxqP51+1sj5MtKPDZjHWhwQYKrVKyvfAdAbvb+Yc5e9/450JPBW9EJp6cPsKjF8HRfgfc+rTBSUnb2FTj1raMlLbgZbFANQb0V8J//cDA3RI8akFn3zsytXOsWeAXvlUszhl+HA6kmmXEniBGtFcrOl0MsuOI8WnmnRoOfLP+MWrFXXSpWKxSDol4iURUhioR43PBnCdIJU+eWyZcYUUV9rVAM6lKx4Aq9jQIAWHLG09kfncut6G7fMAAu0aU+YGx10nhnBFxtehH1KsHZKNQAf/7iVNUfkaOhI+z/MuhOiP9o5P8LgDZBOTlEMH8AAAAASUVORK5CYII=")
_ICON_OFF_24 = ("iVBORw0KGgoAAAANSUhEUgAAACEAAAAYCAYAAAB0kZQKAAAC2UlEQVR4nO2WT2xMURTGv3Pvu+91hpchJERLqyJUdWWjCyJEIuzEzFKErQWLRkR5nj8LmUQtrKVhZWpj0VVTCQu1saoqkVZLKySkHa86nbnv3mNBUWHmdcWiv+Qs7uJ9+b53Tu49hF/IFgqyJ5czAHD55r3GuFLaYq1mawXhDwhhWQhFjpt6ef7kkfHfNZLyQ5yZiYj4XP72XiVlB8DtQogMJxCw1hYBGtDG5K92HH0AZgJRrU9/hgGAbLYgiYg7891dda7X7yh1oDRXzkwXP3OxRk0XP3NprpxxlDpQ53r9nfnuLhBxNluQv4asGqRQKMhcLmfOXbvVlcmsOjU19dEYY7CxsV40rV9LRATwX0IRgZkx9vY9vx6ftFJKrFy5WhanPt24evb46aStIQA4f/3OLtdxH5VKs9pTjnNofzu1tWyCI5P9ztgAg8Mj6O0b4LKO41QqrSqlmT2Xz5x4mMSIEwSBMNpcIEXQWovDB3fTju3NiGYrKCfzAADYsX0TAKK79/tFOgUYyItBEOzDULbmbAisaNogJLVHUcTNjfWireWbASHEoiqaraCtpRnNjfUiimZYSrkTqXUNYUg2CAJR1USssVU6apnWGk0NayhpC/6EI4GmhjWk45g9162z5G4GgOetrVUHVABk5w9EiYa5Kgs1fmrXMPHvWTIxz5KJeZZMzCMA/mGE//ZQLYKFGpwopHAUXphYf1FKYWziA8eLWkcWEhtgbOIDK8ehcqUyJ7jyCgC2DQ1VTScwPfbGGh7wfZ9Gxyft4PAo/LQLa+2iyk+7GBwexej4pPX95WSMeYLSu4kgYBGGYdWbU4RhaEnJS8wMpZTt7XvMT5+NwPNcLEsnK89z8fTZCHr7HrNSyjIACXMxDEP7vLWn5lvw/yw12WxB9vTkTGe+u8tzU6dIEKIogtY60aQqpcj3fbBllCulG1c6jp3+rmkB1NT4LxbdBf36Vyv/V3C0ynsC5BOvAAAAAElFTkSuQmCC")
_ICON_ON_36 = ("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")
_ICON_OFF_36 = ("iVBORw0KGgoAAAANSUhEUgAAADIAAAAkCAYAAADLsGk3AAAElklEQVR4nO1ZTWgUZxh+3veb2ZnZKI21cbWEerD0EKtQa0+CRD20V2ldqFCKSIXeeqkkFTq7pTY59lawlR4KFtZary34ExQvxSpo9VBQsISaNbWmSHZmduZ73x52V4htaHayoVHywMcsM7Pv8z7z/T3f9wHzIAxDrtVqZr7neVGr1UwYhtzruM58ZOVy2QJAOP7NoBawh8Bb1GZbrSpogcEVgCECGeeaQq5TE2fL5fLk4xy9wD9y6hCMfHbsJd/vG1XVN92Ct5qIIJKPl9lAVZE2k4dEdCqOZ8fGPzr0ay/FzBHSCTw6frzsFbwv3IL/bBzNQkQsMSv/i/CFQABVEWJm4wd9SJvxn0kzeX9s5GCtV2IeJRaG551qdVd2ZPzr94Ji37FmM0ZmbWaYjahSs5lCRHKRMDMKBRdMpFbEOsY4hYKPqDF76OjIgS873IsWsq9WMyfLZTt69PhbfatXn0ySKBMVNswcRQkC38MLgyU8v/45MHfXT0UEv0/9gd8m64jiBEHgwYoIE4vnBc7sw4f7xo4c/K6TQ24hYRhypVLR0bGvNnme/5MCz1ibwRBzFCfYMrQJu3a8gtLAGnCOtqUARID69AOcv3QV12/eQuB7sCpijAMC/sqsfe3TD9+9XalUqFqt5qp2BsBEpA6bjz2vuMZmqRg2HMUJ9uzcjv17d2Pd2n7ESYpGI8Vso9lVaTRSxEmKdWv7sX/vbuzZuR1RnMCwYZul4nnFNSoSEpHe3Lw5Vx8E2h949PMTJZOmtwkICEAUJ7R1aBPe3rsbUZxCW2rzcgAApD1sB76Lb0+fw7VWzagCgKLBkBerhw9MqSoRkXYbnwHANJuvB0GxKCJiRSjwPQzv2IbMak9EoB1DAWRWMbxjW6t5iZCIiBcEfdbiDQCoVCZyTcKdnvsqQCAmTdMMGwdLKA30o5lmPRHxiIwIzTRDaaAfGwdLSNMMxKQAAUzbFxW7fd0sYsEgsiLYsH4AzAC06xr+b6iCGdiwfgBWBAwiFYGSvtx6YTh3ZwcRzRn2mCnfzLdAUJtj7j1a1KTIAKCqS5n3gqBYXA49d6H/F1aELDesCFluWBGy3LAiZLmhY1GWwFR1B8LicuhYlDnWWaRl35cK2uaYe08XtYfWaVo3mA0EqoYZd6emIQKghxb+EYggAtydmoZhhkCVmEFKv7RemMjV3Dt/+hlQqCi5roM7k3XUp2dQcB1ID628qKLgOqhPz+DOZB2u60BFCVBA9PJiYjMA2ELhxyhqNJiZDbNGcYKJS1fgmJad74WYzlLXMYSJS1fa63ZWZuYkimaNwQ8AUKkM57LzHIahM/bB/jqsPRUEq8iKtUHg49rNWzhz8SoC34XXrhkRhYh0WRSiCs91EPguzly82lqvBz5aXKvIiv2+evjA1L5azeQdeLj1sZQysZ8kSeOBcVy2YiXwPZy9cBknTp/Dvfsz8D0XxaKLvmKhq1IsuvA9F/fuz+DE6XM4e+Fye71uxTguJ0njATFXVZWGbtzIXfVPzwZd58dTsWXawVOxif24mCf6WKGDpTzoqY68syQHPfPiSTt6+xvUcxP/yqEKNgAAAABJRU5ErkJggg==")
_IMG = {
    18: (_ICON_ON_18, _ICON_OFF_18),
    24: (_ICON_ON_24, _ICON_OFF_24),
    36: (_ICON_ON_36, _ICON_OFF_36),
}

_IMG_REFS = []   # 保持 PhotoImage 引用，防止被垃圾回收


def _cfg(style, widget, **kw):
    try:
        style.configure(widget, **kw)
    except Exception:
        pass


def _mp(style, widget, **kw):
    try:
        style.map(widget, **kw)
    except Exception:
        pass


def font(size=10, bold=False):
    return (FONT, size, "bold") if bold else (FONT, size)


def apply(root):
    """给 root 应用现代主题。返回 ttk.Style。"""
    style = ttk.Style(root)
    for theme in ("clam", "alt", "default"):
        try:
            style.theme_use(theme)
            break
        except Exception:
            continue

    root.configure(bg=BG)

    _cfg(style, ".", font=font(10), background=CARD, foreground=TEXT)
    _cfg(style, "TFrame", background=CARD)
    _cfg(style, "TLabel", background=CARD, foreground=TEXT, font=font(10))
    _cfg(style, "Status.TLabel", font=font(11, True), foreground=TEXT)
    _cfg(style, "Hint.TLabel", foreground=MUTED, font=font(9))
    _cfg(style, "Section.TLabel", foreground=PRIMARY, font=font(10, True))

    # ---- 顶栏（鲜明主色）----
    _cfg(style, "Header.TFrame", background=PRIMARY)
    _cfg(style, "Header.TLabel", background=PRIMARY, foreground=HEADER_TX,
         font=font(11, True))
    _cfg(style, "HeaderHint.TLabel", background=PRIMARY, foreground=HEADER_SUB,
         font=font(9))
    _cfg(style, "HeaderDot.TLabel", background=PRIMARY, font=font(14, True))
    _cfg(style, "Header.TButton", background="#ffffff", foreground=PRIMARY,
         bordercolor="#ffffff", focuscolor="#ffffff", font=font(10, True),
         padding=(14, 6))
    _mp(style, "Header.TButton",
        background=[("active", "#eaf1ff"), ("pressed", "#dbe7ff")],
        foreground=[("disabled", "#b9c7e8")])

    # ---- 卡片 / 分组 ----
    _cfg(style, "TLabelframe", background=CARD, bordercolor=BORDER,
         borderwidth=1, relief="solid", padding=10)
    _cfg(style, "TLabelframe.Label", background=CARD, foreground=PRIMARY,
         font=font(10, True))

    # ---- 页签 ----
    _cfg(style, "TNotebook", background=BG, bordercolor=BG, borderwidth=0,
         tabmargins=(0, 8, 0, 0))
    _cfg(style, "TNotebook.Tab", background=BG, foreground=MUTED,
         font=font(10, True), padding=(20, 10), borderwidth=0)
    _mp(style, "TNotebook.Tab",
        background=[("selected", PRIMARY), ("active", PRIMARY_S)],
        foreground=[("selected", "#ffffff"), ("active", PRIMARY)])

    # ---- 表格 ----
    _cfg(style, "Treeview", background=CARD, fieldbackground=CARD,
         foreground=TEXT, rowheight=30, font=font(10), borderwidth=0,
         relief="flat", bordercolor=BORDER)
    _cfg(style, "Treeview.Heading", background=HEAD_BG, foreground=HEAD_FG,
         font=font(10, True), relief="flat", padding=(6, 7), borderwidth=0)
    _mp(style, "Treeview.Heading", background=[("active", "#e2e8f0")])
    _mp(style, "Treeview", background=[("selected", PRIMARY_S)],
        foreground=[("selected", TEXT)])

    # ---- 输入 ----
    _cfg(style, "TEntry", fieldbackground=CARD, foreground=TEXT,
         bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
         insertcolor=TEXT, padding=(6, 5), relief="flat")
    _mp(style, "TEntry", bordercolor=[("focus", PRIMARY)],
        lightcolor=[("focus", PRIMARY)], darkcolor=[("focus", PRIMARY)])
    _cfg(style, "TCombobox", fieldbackground=CARD, background=CARD,
         foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER,
         darkcolor=BORDER, arrowcolor=MUTED, padding=(6, 4), relief="flat")
    _mp(style, "TCombobox", fieldbackground=[("readonly", CARD)],
        bordercolor=[("focus", PRIMARY)],
        lightcolor=[("focus", PRIMARY)], darkcolor=[("focus", PRIMARY)])
    root.option_add("*TCombobox*Listbox.background", CARD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", PRIMARY_S)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)

    # ---- 按钮 ----
    _cfg(style, "TButton", background="#eef2f8", foreground=TEXT,
         bordercolor=BORDER, focuscolor="#eef2f8", font=font(10),
         padding=(12, 6), relief="flat", borderwidth=1)
    _mp(style, "TButton",
        background=[("active", "#e3e9f3"), ("pressed", "#d7dfec")],
        bordercolor=[("focus", PRIMARY)])
    _cfg(style, "Primary.TButton", background=PRIMARY, foreground="#ffffff",
         bordercolor=PRIMARY, focuscolor=PRIMARY, font=font(10, True),
         padding=(14, 7))
    _mp(style, "Primary.TButton",
        background=[("active", PRIMARY_D), ("pressed", PRIMARY_D),
                    ("disabled", "#9db9f0")],
        bordercolor=[("active", PRIMARY_D)])
    _cfg(style, "Success.TButton", background=SUCCESS, foreground="#ffffff",
         bordercolor=SUCCESS, focuscolor=SUCCESS, font=font(10, True),
         padding=(14, 7))
    _mp(style, "Success.TButton",
        background=[("active", SUCCESS_D), ("pressed", SUCCESS_D),
                    ("disabled", "#9bc9ac")],
        bordercolor=[("active", SUCCESS_D)])
    _cfg(style, "Danger.TButton", background=DANGER, foreground="#ffffff",
         bordercolor=DANGER, focuscolor=DANGER, font=font(10, True),
         padding=(14, 7))
    _mp(style, "Danger.TButton",
        background=[("active", DANGER_D), ("pressed", DANGER_D),
                    ("disabled", "#e6a3a3")],
        bordercolor=[("active", DANGER_D)])

    # ---- 其他 ----
    _cfg(style, "TSeparator", background=BORDER)
    _cfg(style, "TScrollbar", background="#c7d0dd", troughcolor=BG,
         bordercolor=BG, arrowcolor=MUTED, relief="flat", arrowsize=14)
    _mp(style, "TScrollbar", background=[("active", "#aab6c8")])

    _install_indicator(style, root)
    return style


def _install_indicator(style, root):
    """安装显示「√」的复选框指示器（替换 clam 默认的「×」）。"""
    try:
        ppp = float(root.tk.call("tk", "scaling"))
    except Exception:
        ppp = 1.3333
    target = 18.0 * ppp / 1.3333
    size = 18 if target < 21 else (24 if target < 30 else 36)
    on_b64, off_b64 = _IMG[size]
    on = tk.PhotoImage(master=root, data=on_b64)
    off = tk.PhotoImage(master=root, data=off_b64)
    _IMG_REFS.append((on, off))   # 保持引用，防止被回收
    style._modern_imgs = (on, off)

    try:
        style.element_create("Modern.indicator", "image", off,
                             ("selected", on), ("disabled", off), sticky="w")
        style.layout("Modern.TCheckbutton", [
            ("Checkbutton.padding", {"sticky": "nswe", "children": [
                ("Modern.indicator", {"side": "left", "sticky": ""}),
                ("Checkbutton.focus", {"side": "left", "sticky": "nswe", "children": [
                    ("Checkbutton.label", {"sticky": "nswe"})]})]})])
    except Exception:
        # 同一进程内多次应用（如自动化测试）时元素已存在，忽略即可
        pass
    _cfg(style, "Modern.TCheckbutton", background=CARD, foreground=TEXT,
         focuscolor=CARD, font=font(10), padding=(2, 4))
    _mp(style, "Modern.TCheckbutton",
        background=[("active", CARD)],
        foreground=[("disabled", MUTED)])


def checkbutton(parent, text, variable, command=None, **kw):
    """创建使用现代样式（显示「√」）的复选框。"""
    return ttk.Checkbutton(parent, text=text, variable=variable,
                           command=command, style="Modern.TCheckbutton", **kw)
