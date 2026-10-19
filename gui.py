# -*- coding: utf-8 -*-
"""图形界面：主窗口（顶部状态条 + 四个功能页签）与程序入口。"""

import ctypes
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    import theme
    from table import GridTable
    HAS_TK = True
except ImportError:  # 无 tkinter 环境仍可导入代理逻辑（便于自动化测试）
    HAS_TK = False

from config import load_config, save_config
from constants import (APP_TITLE, APP_VERSION, DEFAULT_LAYERS, HELP_TEXT,
                       IS_WINDOWS, LAYER_GROUPS, LAYERS, LOG_MAX_LINES)
from proxy import TileProxy
from tray import TrayIcon
from utils import (app_base_dir, autostart_supported, default_config_path,
                   enable_dpi_awareness, find_free_port, get_autostart,
                   human_size, port_available, set_autostart)

_Base = tk.Tk if HAS_TK else object


class App(_Base):
    """主窗口：顶部状态条 + 四个功能页签。"""

    def __init__(self):
        super().__init__()
        self.config_data = load_config()
        self.proxy = TileProxy(self.config_data, log_callback=self._push_log)
        self.proxy.verbose = bool(self.config_data.get("verbose_log", False))

        self.dpi_scale = self._apply_dpi_scaling()
        self.title("%s v%s" % (APP_TITLE, APP_VERSION))
        self.minsize(int(880 * self.dpi_scale), int(620 * self.dpi_scale))
        geo = self.config_data.get("geometry")
        if not geo:
            geo = "%dx%d" % (int(980 * self.dpi_scale), int(730 * self.dpi_scale))
        try:
            self.geometry(geo)
        except Exception:
            self.geometry("980x730")

        self.log_q = queue.Queue()
        self.tray_q = queue.Queue()
        self._log_lines = []
        self._log_paused = False
        self._last_stats = {}
        self._tray = None
        self._scanning = False
        self._tick_count = 0
        self._quitting = False

        self._setup_style()
        self._build_menu()
        self._build_ui()
        self._bind_events()
        self._refresh_tokens()
        self._refresh_urls()
        self._update_server_state()
        self._update_cache_path_label(check=True)   # 启动即显示缓存真实位置并校验可写
        self._refresh_cache_info()
        self._auto_clean_on_start()                 # 按设置自动清理一次

        self._init_tray()
        self.after(300, self._drain_log)
        self.after(1000, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._push_ui_log("提示：先在「密钥管理」添加天地图密钥，再点「启动服务」。")
        self._push_ui_log("首次使用请点菜单「帮助 → 使用步骤」，内含申请密钥的完整指引。")

    def _apply_dpi_scaling(self):
        """按系统 DPI 调整 Tk 缩放，返回缩放系数（1.0 表示标准 96 DPI）。

        全程保护：任何一步失败都退回 1.0，绝不影响程序启动。
        """
        if not IS_WINDOWS:
            return 1.0
        hdc = None
        try:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            hdc = user32.GetDC(0)
            if not hdc:
                return 1.0
            dpi = gdi32.GetDeviceCaps(hdc, 88)      # LOGPIXELSX
            if dpi and 96 < dpi <= 480:
                scale = dpi / 96.0
                self.tk.call("tk", "scaling", dpi / 72.0)
                return scale
        except Exception:
            pass
        finally:
            try:
                if hdc:
                    ctypes.windll.user32.ReleaseDC(0, hdc)
            except Exception:
                pass
        return 1.0

    # ------------------------------------------------------------------ 样式
    def _setup_style(self):
        theme.apply(self)

    def _build_menu(self):
        menubar = tk.Menu(self)

        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="保存配置", command=self._save_now)
        m_file.add_command(label="导出配置…", command=self._export_config)
        m_file.add_command(label="导入配置…", command=self._import_config)
        m_file.add_separator()
        self.autostart_var = tk.BooleanVar(value=get_autostart())
        m_file.add_checkbutton(label="开机自动启动", variable=self.autostart_var,
                               command=self._toggle_autostart)
        m_file.add_separator()
        m_file.add_command(label="退出", command=self._real_quit)
        menubar.add_cascade(label="文件", menu=m_file)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="使用步骤 / 密钥申请", command=self._show_help)
        m_help.add_command(label="打开天地图官网申请密钥",
                           command=lambda: webbrowser.open("https://www.tianditu.gov.cn/"))
        m_help.add_command(label="天地图地图服务说明",
                           command=lambda: webbrowser.open(
                               "http://lbs.tianditu.gov.cn/server/MapService.html"))
        m_help.add_separator()
        m_help.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=m_help)

        self.configure(menu=menubar)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # ---------- 顶部常驻状态条 ----------
        bar = ttk.Frame(self, style="Header.TFrame", padding=(14, 10))
        bar.pack(fill="x")
        self.status_dot = ttk.Label(bar, text="●", style="HeaderDot.TLabel",
                                    foreground="#a8b6d6")
        self.status_dot.pack(side="left")
        self.status_text = ttk.Label(bar, text="已停止", style="Header.TLabel")
        self.status_text.pack(side="left", padx=(6, 18))
        self.stats_text = ttk.Label(bar, text="请求 0 · 缓存命中 0 · 错误 0",
                                    style="HeaderHint.TLabel")
        self.stats_text.pack(side="left")
        self.btn_stop = ttk.Button(bar, text="■ 停止服务", style="Danger.TButton",
                                   command=self._stop_server, state="disabled")
        self.btn_stop.pack(side="right", padx=3)
        self.btn_start = ttk.Button(bar, text="▶ 启动服务", style="Success.TButton",
                                    command=self._start_server)
        self.btn_start.pack(side="right", padx=3)

        # ---------- 页签 ----------
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._tab_service()
        self._tab_tokens()
        self._tab_layers()
        self._tab_log()

    # ---- 页签 1：服务与地址 ----
    def _tab_service(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="  服务与地址  ")

        ttk.Label(tab, text="提示：先「启动服务」，再到 ArcMap 的「添加 WMTS 服务器」里粘贴下面的地址。",
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 6))

        frm = ttk.LabelFrame(tab, text="服务设置")
        frm.pack(fill="x", pady=(0, 8))

        row1 = ttk.Frame(frm)
        row1.pack(fill="x", pady=(2, 5))
        ttk.Label(row1, text="端口：").pack(side="left")
        self.port_var = tk.StringVar(value=str(self.config_data["port"]))
        ttk.Entry(row1, textvariable=self.port_var, width=9).pack(side="left", padx=(0, 4))
        ttk.Button(row1, text="检测", width=6,
                   command=self._detect_port).pack(side="left", padx=(0, 24))
        ttk.Label(row1, text="协议：").pack(side="left")
        self.scheme_var = tk.StringVar(value=self.config_data["scheme"])
        ttk.Combobox(row1, textvariable=self.scheme_var, values=["http", "https"],
                     width=7, state="readonly").pack(side="left", padx=(0, 24))
        ttk.Label(row1, text="接口：").pack(side="left")
        self.mode_var = tk.StringVar(value=self.config_data["mode"])
        ttk.Combobox(row1, textvariable=self.mode_var, values=["esri", "ogc"],
                     width=7, state="readonly").pack(side="left")
        ttk.Label(row1, text="esri 已修正分辨率，ArcMap 里不会整体偏移",
                  style="Hint.TLabel").pack(side="left", padx=(10, 0))

        # 安全相关：默认只允许本机访问
        row1b = ttk.Frame(frm)
        row1b.pack(fill="x", pady=(0, 5))
        self.local_only_var = tk.BooleanVar(
            value=bool(self.config_data.get("local_only", True)))
        theme.checkbutton(row1b, text="仅本机可访问（推荐，防止局域网内他人借用密钥）",
                          variable=self.local_only_var,
                          command=self._on_local_only_toggle).pack(side="left")

        row2 = ttk.Frame(frm)
        row2.pack(fill="x", pady=(0, 5))
        self.cache_var = tk.BooleanVar(value=self.config_data["cache_enabled"])
        theme.checkbutton(row2, text="本地缓存", variable=self.cache_var,
                          command=self._on_cache_toggle).pack(side="left")
        ttk.Label(row2, text="缓存目录：").pack(side="left", padx=(24, 4))
        self.cache_dir_var = tk.StringVar(value=self.config_data["cache_dir"])
        self.cache_dir_var.trace_add("write",
                                     lambda *a: self._update_cache_path_label())
        ttk.Entry(row2, textvariable=self.cache_dir_var).pack(
            side="left", fill="x", expand=True)
        ttk.Button(row2, text="浏览", width=6,
                   command=self._browse_cache_dir).pack(side="left", padx=(6, 0))

        row3 = ttk.Frame(frm)
        row3.pack(fill="x")
        self.tray_var = tk.BooleanVar(value=self.config_data.get("close_to_tray", True))
        theme.checkbutton(row3, text="关闭窗口时最小化到托盘",
                          variable=self.tray_var).pack(side="left")
        self.verbose_var = tk.BooleanVar(value=self.config_data.get("verbose_log", False))
        theme.checkbutton(row3, text="详细日志（逐条记录瓦片，排障用）",
                          variable=self.verbose_var,
                          command=self._toggle_verbose).pack(side="left", padx=(24, 0))

        # 缓存实际位置（让用户一眼看到缓存到底存哪了、有没有生效）
        row4 = ttk.Frame(frm)
        row4.pack(fill="x", pady=(6, 0))
        ttk.Label(row4, text="缓存位置：").pack(side="left")
        self.cache_path_label = ttk.Label(row4, text="—", foreground="#444444")
        self.cache_path_label.pack(side="left")
        ttk.Button(row4, text="打开目录", command=self._open_cache_dir).pack(
            side="left", padx=8)
        ttk.Button(row4, text="刷新统计",
                   command=lambda: self._refresh_cache_info(check=True,
                                                            verbose=True)).pack(side="left")
        self.cache_stat_label = ttk.Label(row4, text="", style="Hint.TLabel")
        self.cache_stat_label.pack(side="left", padx=(10, 0))

        # 缓存清理：体积上限 / 过期天数（0 = 不限制）
        row5 = ttk.Frame(frm)
        row5.pack(fill="x", pady=(6, 0))
        ttk.Label(row5, text="自动清理：").pack(side="left")
        self.cache_max_var = tk.StringVar(
            value=str(self.config_data.get("cache_max_mb", 1024)))
        ttk.Label(row5, text="超过").pack(side="left", padx=(4, 2))
        ttk.Entry(row5, textvariable=self.cache_max_var, width=7).pack(side="left")
        ttk.Label(row5, text="MB").pack(side="left", padx=(2, 10))
        self.cache_days_var = tk.StringVar(
            value=str(self.config_data.get("cache_expire_days", 30)))
        ttk.Label(row5, text="或超过").pack(side="left")
        ttk.Entry(row5, textvariable=self.cache_days_var, width=5).pack(side="left",
                                                                       padx=(4, 2))
        ttk.Label(row5, text="天").pack(side="left", padx=(2, 10))
        ttk.Label(row5, text="（0 = 不限制）", style="Hint.TLabel").pack(side="left")
        ttk.Button(row5, text="立即清理", command=self._clean_cache_now).pack(
            side="left", padx=(10, 4))
        ttk.Button(row5, text="清空全部", command=self._clear_cache_all).pack(
            side="left")

        # 连接地址
        addr = ttk.LabelFrame(tab, text="ArcMap 连接地址（「添加 WMTS 服务器」时填写）")
        addr.pack(fill="both", expand=True)

        cols = [
            {"id": "layer", "title": "图层", "width": 96, "anchor": "center",
             "font": theme.font(10, True)},
            {"id": "name", "title": "说明", "width": 190, "anchor": "w"},
            {"id": "url", "title": "URL", "width": 380, "weight": 1, "anchor": "w",
             "font": theme.MONO},
        ]
        self.url_table = GridTable(addr, columns=cols, on_activate=self._copy_url)
        self.url_table.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)

        btns = ttk.Frame(addr)
        btns.pack(side="left", fill="y", padx=8, pady=8)
        ttk.Button(btns, text="复制选中", command=self._copy_url).pack(fill="x", pady=3)
        ttk.Button(btns, text="复制全部", command=self._copy_all_urls).pack(fill="x", pady=3)
        ttk.Separator(btns, orient="horizontal").pack(fill="x", pady=6)
        ttk.Button(btns, text="打开测试页", command=self._open_local_page).pack(fill="x", pady=3)
        ttk.Button(btns, text="保存配置", style="Primary.TButton",
                   command=self._save_now).pack(fill="x", pady=3)

    # ---- 页签 2：密钥管理 ----
    def _tab_tokens(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="  密钥管理  ")

        tip = ttk.Label(
            tab,
            text="天地图密钥（tk）必须是「服务端」类型；多个密钥会按当日用量自动轮换。"
                 "双击某行可查看完整密钥。",
            style="Hint.TLabel")
        tip.pack(anchor="w", pady=(0, 6))

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True)

        # 密钥排在第一列；各列按窗口宽度自适应（weight）
        cols = [
            {"id": "token", "title": "密钥（tk）", "width": 240, "weight": 4,
             "anchor": "w", "font": theme.MONO},
            {"id": "desc", "title": "备注", "width": 120, "weight": 2, "anchor": "w"},
            {"id": "limit", "title": "配额上限", "width": 90, "weight": 0,
             "anchor": "center"},
            {"id": "used", "title": "已用", "width": 80, "weight": 0,
             "anchor": "center"},
            {"id": "active", "title": "状态", "width": 70, "weight": 0,
             "anchor": "center"},
        ]
        self.token_table = GridTable(body, columns=cols,
                                     on_activate=self._show_full_token)
        self.token_table.pack(side="left", fill="both", expand=True, padx=(0, 8))

        btns = ttk.Frame(body)
        btns.pack(side="left", fill="y")
        ttk.Button(btns, text="＋ 添加", style="Primary.TButton",
                   command=self._add_token).pack(fill="x", pady=3)
        for text, cmd in (("✎ 编辑", self._edit_token),
                          ("✕ 删除", self._delete_token),
                          ("启用 / 停用", self._toggle_token),
                          ("重置用量", self._reset_usage_ui)):
            ttk.Button(btns, text=text, command=cmd).pack(fill="x", pady=3)
        ttk.Separator(btns, orient="horizontal").pack(fill="x", pady=6)
        ttk.Button(btns, text="⟳ 测试密钥", style="Primary.TButton",
                   command=self._test_tokens).pack(fill="x", pady=3)

    # ---- 页签 3：底图选择 ----
    def _tab_layers(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="  底图选择  ")

        ttk.Label(tab, text="勾选需要的底图，连接地址会同步更新。",
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 8))

        grid = ttk.Frame(tab)
        grid.pack(fill="x", anchor="w")
        self.layer_vars = {}
        selected = self.config_data.get("layers", DEFAULT_LAYERS)
        for col, (group, items) in enumerate(LAYER_GROUPS):
            box = ttk.LabelFrame(grid, text=group)
            box.grid(row=col // 3, column=col % 3, sticky="nsew",
                     padx=6, pady=6, ipadx=8, ipady=4)
            for key, label in items:
                var = tk.BooleanVar(value=(key in selected))
                self.layer_vars[key] = var
                theme.checkbutton(box, text="%s   (%s)" % (label, key),
                                  variable=var,
                                  command=self._on_layers_changed).pack(anchor="w")
        for c in range(3):
            grid.columnconfigure(c, weight=1)

        ops = ttk.Frame(tab)
        ops.pack(fill="x", pady=(10, 0))
        ttk.Button(ops, text="推荐（4 个常用底图）",
                   command=self._pick_recommended).pack(side="left", padx=3)
        ttk.Button(ops, text="全选", command=lambda: self._pick_layers(all_on=True)).pack(
            side="left", padx=3)
        ttk.Button(ops, text="清空", command=lambda: self._pick_layers(all_on=False)).pack(
            side="left", padx=3)

        self.layer_count_label = ttk.Label(tab, text="", style="Hint.TLabel")
        self.layer_count_label.pack(anchor="w", pady=(8, 0))

    # ---- 页签 4：运行日志 ----
    def _tab_log(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="  运行日志  ")

        ops = ttk.Frame(tab)
        ops.pack(fill="x", pady=(0, 6))
        ttk.Button(ops, text="清空", command=self._clear_log).pack(side="left", padx=3)
        ttk.Button(ops, text="导出到文件…", command=self._export_log).pack(side="left", padx=3)
        self.pause_var = tk.BooleanVar(value=False)
        theme.checkbutton(ops, text="暂停滚动",
                          variable=self.pause_var).pack(side="left", padx=12)
        ttk.Label(ops, text="（只记录关键事件；如需逐条瓦片日志请勾选「详细日志」）",
                  style="Hint.TLabel").pack(side="left")

        wrap = ttk.Frame(tab)
        wrap.pack(fill="both", expand=True)
        self.log_text = tk.Text(wrap, height=14, state="disabled", wrap="none",
                                font=("Consolas", 10), background="#0f172a",
                                foreground="#cbd5e1", insertbackground="#38bdf8",
                                selectbackground="#334155", relief="flat",
                                borderwidth=0, padx=8, pady=6)
        yscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.log_text.yview)
        xscroll = ttk.Scrollbar(wrap, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        yscroll.pack(side="right", fill="y")
        xscroll.pack(side="bottom", fill="x")
        self.log_text.pack(side="left", fill="both", expand=True)

    # ------------------------------------------------------------------ 事件
    def _bind_events(self):
        self.port_var.trace_add("write", lambda *a: None)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_tray(self):
        self._tray = TrayIcon("%s v%s" % (APP_TITLE, APP_VERSION),
                              lambda act: self.tray_q.put(act))
        self._tray.start()
        if self._tray.available:
            self._push_ui_log("系统托盘已就绪：点关闭按钮会最小化到托盘，双击图标可恢复。")
            if not getattr(sys, "frozen", False):
                self._push_ui_log("提示：源码运行时托盘可能不显示图标（缺少 icon.ico），"
                                  "打包成 exe 后会正常。")
        else:
            self._push_ui_log("系统托盘不可用（%s）。" % (self._tray.error or "未知原因"))
            self._push_ui_log("已自动改为：关闭窗口即退出程序，不会留下后台进程。")
            try:
                self.tray_var.set(False)
                self.config_data["close_to_tray"] = False
            except Exception:
                pass

    # ------------------------------------------------------------------ 定时
    def _tick(self):
        # 托盘动作 / 后台任务结果（线程安全队列）
        while True:
            try:
                act = self.tray_q.get_nowait()
            except queue.Empty:
                break
            if isinstance(act, tuple):
                self._handle_async(act)
            else:
                self._handle_tray(act)
        self._update_stats()
        if self.proxy.is_running():
            self._refresh_token_usage()
        # 每 5 秒后台统计一次缓存（不阻塞界面）
        self._tick_count += 1
        if self._tick_count % 5 == 0 and self.cache_var.get():
            self._refresh_cache_info()
        self.after(1000, self._tick)

    def _handle_async(self, item):
        """处理后台线程回传的结果（密钥测试、缓存统计等）。"""
        kind, payload = item[0], item[1] if len(item) > 1 else None
        if kind == "test_done":
            messagebox.showinfo("密钥测试结果", payload or "（无结果）")
        elif kind == "cache_info":
            n, total, verbose, ok, why = payload
            text = "已缓存 %s 张 / %s" % (n, self._human_size(total))
            if not ok:
                text += "　⚠ %s" % why
            self.cache_stat_label.configure(
                text=text, foreground="#444444" if ok else "#c0392b")
            if verbose:
                self._show_report("缓存统计", self.proxy.cache_report())
        elif kind == "cache_cleaned":
            r = payload
            self._push_ui_log("缓存清理完成：过期 %d 张、超限 %d 张，释放 %s。"
                              % (r.get("expired", 0), r.get("size_trimmed", 0),
                                 self._human_size(r.get("freed", 0))))
            self._refresh_cache_info()
            messagebox.showinfo(
                "缓存清理",
                "清理完成。\n\n"
                "按时间过期删除：%d 张\n"
                "按体积超限删除：%d 张\n"
                "释放空间：%s\n"
                "保留：%d 张 / %.2f MB"
                % (r.get("expired", 0), r.get("size_trimmed", 0),
                   self._human_size(r.get("freed", 0)),
                   r.get("files", 0), r.get("kept_mb", 0)))
        elif kind == "cache_clean_failed":
            messagebox.showerror("清理失败", str(payload))
        elif kind == "cache_autoclean":
            r = payload
            self._push_ui_log("已自动清理缓存：过期 %d 张、超限 %d 张，释放 %s。"
                              % (r.get("expired", 0), r.get("size_trimmed", 0),
                                 self._human_size(r.get("freed", 0))))
            self._refresh_cache_info()

    def _show_report(self, title, text):
        """用一个可滚动、可复制的窗口展示长文本报告（比 messagebox 好用）。"""
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("820x600")
        win.transient(self)
        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)
        txt = tk.Text(frm, wrap="none", font=("Consolas", 9),
                      background="#fbfbfb", relief="solid", borderwidth=1)
        ysb = ttk.Scrollbar(frm, orient="vertical", command=txt.yview)
        xsb = ttk.Scrollbar(frm, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", text)

        bar = ttk.Frame(win, padding=(10, 0, 10, 10))
        bar.pack(fill="x")

        def copy_all():
            self.clipboard_clear()
            self.clipboard_append(text)
            self._push_ui_log("报告已复制到剪贴板。")

        ttk.Button(bar, text="复制全部内容", command=copy_all).pack(side="left")
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right")
        txt.focus_set()

    def _handle_tray(self, act):
        if act == "show":
            self.deiconify()
            self.lift()
            self.focus_force()
        elif act == "start":
            self._start_server()
        elif act == "stop":
            self._stop_server()
        elif act == "quit":
            self._real_quit()

    def _update_stats(self):
        st = self.proxy.get_stats()
        extra = ""
        if st.get("tile"):
            extra = " · 写入 %d" % self.proxy.cache_written
            if self.proxy.cache_errors:
                extra += " · 写失败 %d" % self.proxy.cache_errors
        key = (tuple(sorted(st.items())), self.proxy.cache_written,
               self.proxy.cache_errors)
        if key == self._last_stats:
            return
        self._last_stats = key
        self.stats_text.configure(
            text="请求 %d · 缓存命中 %d · 错误 %d%s" %
                 (st.get("total", 0), st.get("cache_hit", 0), st.get("error", 0),
                  extra))

    # ------------------------------------------------------------------ 日志
    def _push_log(self, msg):
        self.log_q.put(msg)

    def _push_ui_log(self, msg):
        self._push_log(msg)

    def _drain_log(self):
        """批处理写入，最多 300ms 一次，避免逐条插入造成卡顿。"""
        if not self._log_paused:
            buf = []
            try:
                while len(buf) < 300:
                    buf.append(self.log_q.get_nowait())
            except queue.Empty:
                pass
            if buf:
                self._log_lines.extend(buf)
                overflow = len(self._log_lines) - LOG_MAX_LINES
                if overflow > 0:
                    del self._log_lines[:overflow]
                    self._rewrite_log()
                else:
                    self._append_log_lines(buf)
        self.after(300, self._drain_log)

    def _append_log_lines(self, lines):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", "\n".join(lines) + "\n")
        self.log_text.configure(state="disabled")
        if not self.pause_var.get():
            self.log_text.see("end")

    def _rewrite_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", "\n".join(self._log_lines) + "\n")
        self.log_text.configure(state="disabled")
        if not self.pause_var.get():
            self.log_text.see("end")

    def _clear_log(self):
        self._log_lines = []
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _export_log(self):
        path = filedialog.asksaveasfilename(
            title="导出日志", defaultextension=".txt",
            initialfile="tianditu_log_%s.txt" % time.strftime("%Y%m%d_%H%M%S"),
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self._log_lines))
            self._push_ui_log("日志已导出到：%s" % path)
            messagebox.showinfo("导出成功", "日志已导出到：\n%s" % path)
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def _toggle_verbose(self):
        """切换详细日志。必须同时更新 config_data，否则会被 _sync_config 覆盖回 False。"""
        on = bool(self.verbose_var.get())
        self.proxy.verbose = on
        self.config_data["verbose_log"] = on
        save_config(self.config_data)
        self._push_ui_log("详细日志：%s%s" % (
            "已开启" if on else "已关闭",
            "（将逐条记录每张瓦片，ArcMap 出图时日志会很多）" if on else ""))

    # ------------------------------------------------------------------ 配置
    def _sync_config(self):
        """把界面上的设置写回配置字典（**就地修改**，保证 proxy 能立刻看到）。

        注意：必须用 update() 而不是重新赋值，否则 self.proxy.config 会指向
        旧字典，导致「改了缓存目录却不生效」这类问题。
        """
        try:
            self.config_data["port"] = int(self.port_var.get() or 80)
        except (ValueError, TypeError):
            self.config_data["port"] = 80
        self.config_data["scheme"] = self.scheme_var.get()
        self.config_data["mode"] = self.mode_var.get()
        try:
            self.config_data["local_only"] = bool(self.local_only_var.get())
        except AttributeError:
            self.config_data["local_only"] = True
        self.config_data["cache_enabled"] = bool(self.cache_var.get())
        self.config_data["cache_dir"] = self.cache_dir_var.get().strip() or "cache"
        try:
            self.config_data["cache_max_mb"] = max(0, int(self.cache_max_var.get() or 0))
        except (ValueError, AttributeError):
            self.config_data["cache_max_mb"] = 1024
        try:
            self.config_data["cache_expire_days"] = max(
                0, int(self.cache_days_var.get() or 0))
        except (ValueError, AttributeError):
            self.config_data["cache_expire_days"] = 30
        self.config_data["layers"] = [k for k, v in self.layer_vars.items() if v.get()]
        self.config_data["close_to_tray"] = bool(self.tray_var.get())
        self.config_data["verbose_log"] = bool(self.verbose_var.get())
        if autostart_supported():
            self.config_data["autostart"] = get_autostart()
        try:
            self.config_data["geometry"] = self.geometry()
        except Exception:
            pass
        # 兜底：确保 proxy 与界面用的是同一个字典
        if self.proxy.config is not self.config_data:
            self.proxy.config.clear()
            self.proxy.config.update(self.config_data)
            self.config_data = self.proxy.config
        self.proxy.verbose = bool(self.config_data.get("verbose_log", False))
        save_config(self.config_data)

    def _save_now(self):
        self._sync_config()
        self._push_ui_log("配置已保存到：%s" % default_config_path())

    def _export_config(self):
        self._sync_config()
        path = filedialog.asksaveasfilename(
            title="导出配置", defaultextension=".json",
            initialfile="tianditu_config.json",
            filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            save_config(self.config_data, path)
            self._push_ui_log("配置已导出到：%s" % path)
            messagebox.showinfo("导出成功", "配置已导出到：\n%s" % path)
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def _import_config(self):
        path = filedialog.askopenfilename(
            title="导入配置", filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        if not messagebox.askyesno("确认", "导入将覆盖当前配置，确定继续？"):
            return
        try:
            new_cfg = load_config(path)
            # 就地更新，保持与 proxy.config 的同一性
            self.config_data.clear()
            self.config_data.update(new_cfg)
            self.proxy.config = self.config_data
            self.proxy.verbose = bool(new_cfg.get("verbose_log", False))
            # 刷新界面
            self.port_var.set(str(new_cfg["port"]))
            self.scheme_var.set(new_cfg["scheme"])
            self.mode_var.set(new_cfg["mode"])
            self.local_only_var.set(bool(new_cfg.get("local_only", True)))
            self.cache_var.set(bool(new_cfg["cache_enabled"]))
            self.cache_dir_var.set(new_cfg["cache_dir"])
            self.tray_var.set(bool(new_cfg.get("close_to_tray", True)))
            self.verbose_var.set(bool(new_cfg.get("verbose_log", False)))
            for k, v in self.layer_vars.items():
                v.set(k in new_cfg.get("layers", []))
            self._refresh_tokens()
            self._refresh_urls()
            self._update_cache_path_label(check=True)
            self._refresh_cache_info()
            self._save_now()
            self._push_ui_log("已导入配置：%s" % path)
            messagebox.showinfo("导入成功", "配置已导入。")
        except Exception as e:
            messagebox.showerror("导入失败", str(e))

    def _toggle_autostart(self):
        ok, msg = set_autostart(bool(self.autostart_var.get()))
        if not ok:
            self.autostart_var.set(get_autostart())
            messagebox.showwarning("提示", msg)
        else:
            self._push_ui_log(msg)

    # ------------------------------------------------------------------ 服务
    def _detect_port(self):
        # 服务正跑在自己这个端口上，它就是能用的，不要因为「被自己占用」而换掉
        try:
            current = int(self.port_var.get())
        except (TypeError, ValueError):
            current = None
        if self.proxy.is_running() and current == self.proxy.port:
            self._push_ui_log("服务正在使用端口 %d，该端口可用。" % current)
            messagebox.showinfo("端口检测", "服务正在使用端口 %d，它是可用的。" % current)
            return

        p = find_free_port()
        if p is None:
            messagebox.showwarning("检测失败", "没有找到可用端口，请手动填写。")
            return
        self.port_var.set(str(p))
        self._push_ui_log("已选择可用端口：%d" % p)

    def _check_port_or_switch(self):
        """启动前检查端口；被占用时询问是否自动改用可用端口。

        返回最终的端口号，或 None 表示用户放弃启动。
        """
        port = self.config_data["port"]
        if port_available(port):
            return port
        alt = find_free_port()
        if alt and messagebox.askyesno(
                "端口被占用",
                "端口 %d 已被其它程序占用（或不允许绑定）。\n\n"
                "是否自动改用可用端口 %d？" % (port, alt)):
            self.port_var.set(str(alt))
            self._sync_config()
            return alt
        return None

    def _start_server(self):
        self._sync_config()
        # 启动时清空内存缓存：确保「改了缓存目录/刚打开程序」后一定按当前目录走
        self.proxy.invalidate_mem_cache()
        if not any(t.get("active") and t.get("token") for t in self.config_data["tokens"]):
            messagebox.showwarning("缺少密钥", "请先到「密钥管理」添加并启用至少一个天地图密钥。")
            self.nb.select(1)
            return

        port = self._check_port_or_switch()
        if port is None:
            return

        try:
            self.proxy.start()
        except OSError as e:
            messagebox.showerror(
                "启动失败",
                "无法监听端口 %d：%s\n\n可尝试：\n"
                "1. 点「检测」换一个可用端口（推荐 8080、12303 等）；\n"
                "2. 确认该端口没有被其它程序（如 IIS、其它代理）占用。"
                % (port, e))
            return
        self._update_server_state()

    def _stop_server(self):
        self.proxy.stop()
        self._update_server_state()

    def _update_server_state(self):
        running = self.proxy.is_running()
        if running:
            self.status_dot.configure(foreground="#4ade80")
            self.status_text.configure(text="运行中  http://localhost:%d/" % self.proxy.port)
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
        else:
            self.status_dot.configure(foreground="#a8b6d6")
            self.status_text.configure(text="已停止")
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
        self._refresh_urls()

    def _open_local_page(self):
        if not self.proxy.is_running():
            messagebox.showinfo("提示", "请先启动服务。")
            return
        webbrowser.open("http://localhost:%d/" % self.proxy.port)

    # ------------------------------------------------------------------ 密钥
    def _refresh_tokens(self):
        rows = []
        for t in self.config_data["tokens"]:
            # 完整显示密钥，不再截断；列宽由界面自适应
            limit = "不限" if t.get("limit", 0) <= 0 else str(t.get("limit", 0))
            rows.append({
                "disabled": not t.get("active"),
                "values": {
                    "token": t.get("token", ""),
                    "desc": t.get("description", ""),
                    "limit": limit,
                    "used": t.get("used", 0),
                    "active": "启用" if t.get("active") else "停用",
                },
            })
        self.token_table.set_rows(rows)

    def _show_full_token(self, index=None):
        """双击查看完整密钥（便于核对，也方便复制）。"""
        if index is None:
            index = self.token_table.selected_index()
        if index is None:
            return
        idx = index
        if idx >= len(self.config_data["tokens"]):
            return
        t = self.config_data["tokens"][idx]

        win = tk.Toplevel(self)
        win.title("查看密钥")
        win.transient(self)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="密钥（tk）：").grid(row=0, column=0, sticky="e", pady=6)
        var = tk.StringVar(value=t.get("token", ""))
        ent = ttk.Entry(frm, textvariable=var, width=46, state="readonly")
        ent.grid(row=0, column=1, pady=6)
        ttk.Label(frm, text="备注：").grid(row=1, column=0, sticky="e", pady=6)
        ttk.Label(frm, text=t.get("description", "") or "（无）").grid(
            row=1, column=1, sticky="w", pady=6)

        def copy_it():
            self.clipboard_clear()
            self.clipboard_append(var.get())
            self._push_ui_log("已复制密钥到剪贴板。")

        ttk.Button(frm, text="复制", command=copy_it).grid(row=2, column=1,
                                                           sticky="e", pady=(4, 0))
        ttk.Button(frm, text="关闭", command=win.destroy).grid(row=2, column=0,
                                                               sticky="w", pady=(4, 0))

    def _refresh_token_usage(self):
        """只更新「已用」列，避免整表重建造成的闪烁与开销。"""
        for i, t in enumerate(self.config_data["tokens"]):
            if i >= self.token_table.row_count():
                break
            self.token_table.set_cell(i, "used", t.get("used", 0))

    def _selected_token_index(self):
        return self.token_table.selected_index()

    def _token_editor(self, title, values=None):
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)
        pad = {"padx": 10, "pady": 7}
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="天地图密钥（tk）：").grid(row=0, column=0, sticky="e", **pad)
        token_var = tk.StringVar(value=(values or {}).get("token", ""))
        ttk.Entry(frm, textvariable=token_var, width=44).grid(row=0, column=1, **pad)

        ttk.Label(frm, text="备注：").grid(row=1, column=0, sticky="e", **pad)
        desc_var = tk.StringVar(value=(values or {}).get("description", ""))
        ttk.Entry(frm, textvariable=desc_var, width=44).grid(row=1, column=1, **pad)

        ttk.Label(frm, text="每日配额上限：").grid(row=2, column=0, sticky="e", **pad)
        limit_var = tk.StringVar(value=str((values or {}).get("limit", 10000)))
        ttk.Entry(frm, textvariable=limit_var, width=12).grid(row=2, column=1, sticky="w")
        ttk.Label(frm, text="0 表示不限", style="Hint.TLabel").grid(
            row=2, column=1, sticky="w", padx=(110, 0))

        active_var = tk.BooleanVar(value=(values or {}).get("active", True))
        theme.checkbutton(frm, text="启用该密钥", variable=active_var).grid(
            row=3, column=1, sticky="w", **pad)

        def ok():
            tok = token_var.get().strip()
            if not tok:
                messagebox.showwarning("提示", "密钥不能为空。", parent=win)
                return
            try:
                limit = int(limit_var.get() or 0)
            except ValueError:
                limit = 10000
            win.result = {"token": tok, "description": desc_var.get().strip(),
                          "limit": limit, "active": bool(active_var.get())}
            win.destroy()

        btns = ttk.Frame(win, padding=(14, 0, 14, 14))
        btns.pack(fill="x")
        ttk.Button(btns, text="确定", command=ok).pack(side="right", padx=4)
        ttk.Button(btns, text="取消", command=win.destroy).pack(side="right", padx=4)
        win.result = None
        self.wait_window(win)
        return win.result

    def _add_token(self):
        r = self._token_editor("添加密钥")
        if r:
            r["used"] = 0
            self.config_data["tokens"].append(r)
            self._refresh_tokens()
            self._save_now()

    def _edit_token(self):
        idx = self._selected_token_index()
        if idx is None:
            messagebox.showinfo("提示", "请先选中一个密钥。")
            return
        cur = self.config_data["tokens"][idx]
        r = self._token_editor("编辑密钥", cur)
        if r:
            r["used"] = cur.get("used", 0)
            self.config_data["tokens"][idx] = r
            self._refresh_tokens()
            self._save_now()

    def _delete_token(self):
        idx = self._selected_token_index()
        if idx is None:
            return
        if messagebox.askyesno("确认", "确定删除该密钥？"):
            del self.config_data["tokens"][idx]
            self._refresh_tokens()
            self._save_now()

    def _toggle_token(self):
        idx = self._selected_token_index()
        if idx is None:
            return
        t = self.config_data["tokens"][idx]
        t["active"] = not t.get("active", True)
        self._refresh_tokens()
        self._save_now()

    def _reset_usage_ui(self):
        for t in self.config_data["tokens"]:
            t["used"] = 0
        self._refresh_tokens()
        self._push_ui_log("已重置所有密钥的用量计数。")

    def _test_tokens(self):
        if not self.config_data["tokens"]:
            messagebox.showinfo("提示", "还没有添加密钥。")
            return
        self._push_ui_log("开始测试密钥有效性…")

        def worker():
            results = []
            for t in list(self.config_data["tokens"]):
                ok, msg = self.proxy.test_token(t.get("token", ""))
                results.append((t.get("description") or t.get("token", "")[:8], ok, msg))
                self._push_log("[测试] %s：%s" % (results[-1][0], msg))
            lines = []
            for name, ok, msg in results:
                lines.append("%s %s — %s" % ("✔" if ok else "✘", name, msg))
            self.tray_q.put(("test_done", "\n".join(lines)))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ 底图
    def _on_layers_changed(self):
        self._refresh_urls()

    def _pick_recommended(self):
        for k, v in self.layer_vars.items():
            v.set(k in DEFAULT_LAYERS)
        self._refresh_urls()

    def _pick_layers(self, all_on=True):
        for v in self.layer_vars.values():
            v.set(all_on)
        self._refresh_urls()

    def _refresh_urls(self):
        selected = [k for k, v in self.layer_vars.items() if v.get() and k in LAYERS]
        port = self.config_data.get("port", 80)
        self._url_rows = []
        rows = []
        for key in selected:
            url = "http://localhost:%d/wmts/%s" % (port, key)
            self._url_rows.append(url)
            rows.append({"values": {"layer": key, "name": LAYERS[key], "url": url}})
        self.url_table.set_rows(rows)
        self.layer_count_label.configure(
            text="已选 %d 个底图，共 %d 个连接地址。" % (len(selected), len(selected)))

    def _copy_url(self, index=None):
        if index is None:
            index = self.url_table.selected_index()
        if index is None or index >= len(getattr(self, "_url_rows", [])):
            messagebox.showinfo("提示", "请先选中一行连接地址。")
            return
        url = self._url_rows[index]
        self.clipboard_clear()
        self.clipboard_append(url)
        self._push_ui_log("已复制：%s" % url)

    def _copy_all_urls(self):
        port = self.config_data.get("port", 80)
        lines = []
        for key, var in self.layer_vars.items():
            if var.get() and key in LAYERS:
                lines.append("http://localhost:%d/wmts/%s\t# %s" % (port, key, LAYERS[key]))
        if not lines:
            messagebox.showinfo("提示", "还没有勾选任何底图。")
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self._push_ui_log("已复制全部连接地址（%d 条）。" % len(lines))

    def _browse_cache_dir(self):
        d = filedialog.askdirectory(title="选择缓存目录",
                                    initialdir=self.cache_dir_var.get() or app_base_dir())
        if d:
            self.cache_dir_var.set(d)
            self._apply_cache_dir_change("（缓存目录已改为 %s）" % d)
            self._update_cache_path_label(check=True)
            self._refresh_cache_info()
            self._push_ui_log("缓存目录已改为：%s" % d)

    # ---- 缓存可视化 --------------------------------------------------------
    @staticmethod
    def _human_size(n):
        return human_size(n)

    def _on_local_only_toggle(self):
        self._sync_config()
        on = bool(self.local_only_var.get())
        self._push_ui_log("访问范围已设为：%s%s" % (
            "仅本机" if on else "允许局域网访问",
            "（修改后需重启服务生效）" if self.proxy.is_running() else ""))

    def _on_cache_toggle(self):
        self._sync_config()
        self.proxy.invalidate_mem_cache("（缓存开关已改变）")
        self._update_cache_path_label(check=True)
        self._refresh_cache_info()
        self._push_ui_log("本地缓存已%s。" % ("启用" if self.cache_var.get() else "关闭"))

    def _apply_cache_dir_change(self, reason=""):
        """缓存目录变化后：保存配置 + 清空内存缓存，保证新目录真正生效。"""
        if not hasattr(self, "proxy"):
            return
        self._sync_config()
        self.proxy.invalidate_mem_cache(reason)

    def _update_cache_path_label(self, check=False):
        """显示缓存目录的**绝对路径**；check=True 时顺便探测是否可写。"""
        if not self.cache_var.get():
            self.cache_path_label.configure(text="（未启用缓存）", foreground="#999999")
            self.cache_stat_label.configure(text="")
            return
        if check:
            path, ok, err = self.proxy.cache_dir_status()
            if ok:
                self.cache_path_label.configure(text=path, foreground="#444444")
            else:
                self.cache_path_label.configure(
                    text="%s   ✘ 不可写：%s" % (path, err), foreground="#c0392b")
        else:
            # 只算路径，不做磁盘探测（避免频繁 IO）
            self.cache_path_label.configure(text=self.proxy.cache_dir_path(),
                                            foreground="#444444")

    def _open_cache_dir(self):
        path, ok, err = self.proxy.cache_dir_status()
        if not ok:
            messagebox.showerror("缓存目录不可用",
                                 "目录：\n%s\n\n错误：%s\n\n"
                                 "请点「浏览」换一个可写的目录。" % (path, err))
            return
        try:
            if IS_WINDOWS:
                os.startfile(path)                       # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("打开失败", "%s\n\n请手动打开：\n%s" % (e, path))

    # ---- 缓存清理 ----------------------------------------------------------
    def _clean_cache_now(self):
        self._sync_config()
        max_mb, days = self.proxy.cache_limits()
        if max_mb <= 0 and days <= 0:
            messagebox.showinfo("提示",
                                "当前未设置清理条件（体积上限和过期天数都是 0）。\n"
                                "如需清理，请先填写上限或天数。")
            return
        self._push_ui_log("开始清理缓存（上限 %d MB / 过期 %d 天）…" % (max_mb, days))

        def worker():
            try:
                r = self.proxy.clean_cache()
                self.tray_q.put(("cache_cleaned", r))
            except Exception as e:
                self.tray_q.put(("cache_clean_failed", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _clear_cache_all(self):
        n, total = self.proxy.scan_cache()
        if n == 0:
            messagebox.showinfo("提示", "缓存目录已经是空的。")
            return
        if not messagebox.askyesno(
                "确认清空",
                "将删除缓存目录下的全部内容：\n%s\n\n"
                "共 %d 张瓦片 / %s\n\n确定继续？"
                % (self.proxy.cache_dir_path(), n, self._human_size(total))):
            return
        try:
            freed = self.proxy.clear_all_cache()
            self._push_ui_log("已清空缓存，释放 %s。" % self._human_size(freed))
            self._refresh_cache_info(check=False)
            messagebox.showinfo("完成", "缓存已清空，释放 %s。"
                                % self._human_size(freed))
        except Exception as e:
            messagebox.showerror("清空失败", str(e))

    def _auto_clean_on_start(self):
        """启动时按设置自动清理一次（后台执行，不阻塞界面）。"""
        max_mb, days = self.proxy.cache_limits()
        if max_mb <= 0 and days <= 0:
            return

        def worker():
            try:
                r = self.proxy.clean_cache()
                if r.get("expired") or r.get("size_trimmed"):
                    self.tray_q.put(("cache_autoclean", r))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_cache_info(self, check=False, verbose=False):
        if check:
            self._update_cache_path_label(check=True)
        if not self.cache_var.get():
            self.cache_stat_label.configure(text="（未启用缓存）", foreground="#999999")
            return
        threading.Thread(target=self._scan_cache_async, args=(verbose,),
                         daemon=True).start()

    def _scan_cache_async(self, verbose=False):
        if self._scanning:
            return
        self._scanning = True
        try:
            n, total = self.proxy.scan_cache()
            ok, why = self.proxy.cache_diagnose()
        finally:
            self._scanning = False
        if verbose and not ok:
            self._push_log("[缓存诊断] %s" % why)
        self.tray_q.put(("cache_info", (n, total, verbose, ok, why)))

    # ------------------------------------------------------------------ 帮助
    def _show_help(self):
        win = tk.Toplevel(self)
        win.title("使用步骤 / 密钥申请")
        win.geometry("760x640")
        win.transient(self)
        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)
        txt = tk.Text(frm, wrap="word", font=("Microsoft YaHei UI", 9),
                      background="#fbfbfb", relief="solid", borderwidth=1)
        sb = ttk.Scrollbar(frm, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", HELP_TEXT)
        txt.configure(state="disabled")
        bar = ttk.Frame(win, padding=(10, 0, 10, 10))
        bar.pack(fill="x")
        ttk.Button(bar, text="打开天地图官网申请密钥",
                   command=lambda: webbrowser.open("https://www.tianditu.gov.cn/")).pack(
                       side="left", padx=3)
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right", padx=3)

    def _show_about(self):
        messagebox.showinfo(
            "关于",
            "%s v%s\n\n"
            "把天地图在线底图加载到 ArcMap 的可视化工具。\n"
            "本地瓦片代理 · 多密钥轮换 · 本地缓存 · 托盘运行。\n\n"
            "运行期无任何第三方依赖，不采集、不上传任何信息。"
            % (APP_TITLE, APP_VERSION))

    # ------------------------------------------------------------------ 关闭
    def _on_close(self):
        try:
            self._sync_config()
        except Exception:
            pass
        tray_ok = bool(self._tray and self._tray.available)

        if self.config_data.get("close_to_tray", True) and tray_ok:
            # 托盘可用：收进托盘，服务继续跑
            self.withdraw()
            self._push_ui_log("已最小化到托盘（服务继续运行）。双击托盘图标可恢复窗口。")
            try:
                self._tray.notify(APP_TITLE,
                                  "已最小化到托盘，瓦片服务继续运行。\n双击图标恢复窗口。")
            except Exception:
                pass
            return

        # 托盘不可用：不隐藏窗口（否则会变成「进程还在但找不到界面」的幽灵进程）。
        # 若服务还在运行，提示用户可以选择最小化而不是退出。
        if self.proxy.is_running():
            ans = messagebox.askyesnocancel(
                "关闭确认",
                "瓦片服务正在运行，但系统托盘不可用。\n\n"
                "· 选「是」：最小化到任务栏继续运行（推荐，图标在任务栏上）\n"
                "· 选「否」：停止服务并退出程序\n"
                "· 选「取消」：什么都不做")
            if ans is None:
                return
            if ans:
                self.iconify()
                self._push_ui_log("已最小化到任务栏，服务继续运行（点任务栏图标恢复）。")
                return
        self._real_quit()

    def _real_quit(self):
        """退出程序：按顺序停服务、停托盘、销毁窗口，最后强制保证进程结束。"""
        if getattr(self, "_quitting", False):
            return
        self._quitting = True

        try:
            self._sync_config()
        except Exception:
            pass

        # 1) 停 HTTP 服务（含线程池等待、连接池关闭）
        try:
            self.proxy.stop()
        except Exception:
            pass

        # 2) 停托盘线程并等它真正结束
        try:
            if self._tray:
                self._tray.stop(wait=2.0)
        except Exception:
            pass

        # 3) 销毁主窗口
        try:
            self.destroy()
        except Exception:
            pass

        # 4) 兜底：确保不被遗留的非 daemon 线程卡住进程
        self._force_exit()

    def _force_exit(self, grace=1.0):
        """确保进程真正退出。

        Tk 的 mainloop 返回后，若还有非 daemon 线程（例如某个请求线程
        正好卡在网络读写上），Python 会一直等着，用户看到的就是
        「窗口没了但任务管理器里还有进程」。

        策略：先给正常收尾一点时间，仍不退出才强制结束。
        """
        def leftover():
            return [t for t in threading.enumerate()
                    if t is not threading.current_thread() and t.is_alive()
                    and not t.daemon]

        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass

        # 给解释器/线程池一点收尾时间；大多数情况这里就结束了
        deadline = time.time() + max(0.0, grace)
        while time.time() < deadline:
            if not leftover():
                # 没有非 daemon 线程了，正常返回即可，让解释器自己退出
                return
            time.sleep(0.05)

        left = leftover()
        if left:
            try:
                self._push_log("退出时仍有线程未结束：%s，强制结束进程。"
                               % ", ".join(t.name for t in left[:5]))
                sys.stdout.flush()
            except Exception:
                pass
        # 兜底强制退出；os._exit 不会刷新缓冲，前面已手动 flush
        try:
            os._exit(0)
        except Exception:
            pass


def main():
    if not HAS_TK:
        print("未找到 tkinter，无法启动图形界面。")
        return
    enable_dpi_awareness()
    app = App()
    try:
        app.mainloop()
    finally:
        # mainloop 返回（例如窗口被销毁）后，确保没有任何非 daemon 线程
        # 把进程卡住；托盘线程也必须清理掉，否则图标会残留在任务栏。
        try:
            if not getattr(app, "_quitting", False):
                app._real_quit()
        except Exception:
            pass
