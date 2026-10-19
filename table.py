# -*- coding: utf-8 -*-
"""轻量表格控件 GridTable。

ttk.Treeview 无法为单元格绘制边框或列分隔线，本控件用「Canvas + 网格 Frame」
自绘一张表格，支持：

* 明显的**列分隔线**（每一列之间一条竖线）；
* **隔行底色**与**单元格选中高亮**，行 / 列边界都清晰；
* 纵向滚动，列宽按权重自适应窗口宽度；
* 可选每列的字体（如 URL / 密钥用等宽字体）。

仅依赖 tkinter，配合 theme 的配色使用。
"""

import tkinter as tk
from tkinter import ttk

import theme


class GridTable(ttk.Frame):
    def __init__(self, parent, columns, on_activate=None, row_height=30, **kw):
        super().__init__(parent, **kw)
        self.columns = columns
        self.on_activate = on_activate
        self.row_height = row_height

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.header = tk.Frame(self, background=theme.HEAD_BG)
        self.header.grid(row=0, column=0, sticky="ew")

        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self._yview)
        self.canvas = tk.Canvas(self, background=theme.CARD, highlightthickness=0,
                                bd=0, yscrollcommand=self._on_yscroll)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, rowspan=2, sticky="ns")

        self.body = tk.Frame(self.canvas, background=theme.CARD)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", self._on_wheel)
        self.canvas.bind("<Button-5>", self._on_wheel)

        self._rows = []            # [{cells: {id: label}, base_bg, fg}]
        self._selected = None
        self._grid_cols = self._compute_grid_cols()

        self._build_header()
        self._configure_columns(self.header)
        self._configure_columns(self.body)

    # ------------------------------------------------------------ 布局
    def _compute_grid_cols(self):
        """返回 [(grid_index, column_spec 或 None)]，None 表示列分隔线。"""
        out = []
        gi = 0
        for i, col in enumerate(self.columns):
            out.append((gi, col))
            gi += 1
            if i < len(self.columns) - 1:
                out.append((gi, None))
                gi += 1
        return out

    def _configure_columns(self, frame):
        for gi, col in self._grid_cols:
            if col is None:
                frame.columnconfigure(gi, weight=0, minsize=1)
            elif col.get("weight", 0):
                frame.columnconfigure(gi, weight=col["weight"],
                                       minsize=col.get("width", 80))
            else:
                frame.columnconfigure(gi, weight=0, minsize=col.get("width", 80))

    def _build_header(self):
        for gi, col in self._grid_cols:
            if col is None:
                line = tk.Frame(self.header, width=1, background=theme.CELL_LINE)
                line.grid(row=0, column=gi, sticky="ns")
                continue
            lab = tk.Label(self.header, text=col.get("title", ""), width=1,
                           background=theme.HEAD_BG, foreground=theme.HEAD_FG,
                           anchor=col.get("anchor", "w"), font=theme.font(10, True),
                           padx=8, pady=8)
            lab.grid(row=0, column=gi, sticky="nsew")

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _on_body_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_yscroll(self, first, last):
        self.vsb.set(first, last)

    def _yview(self, *args):
        self.canvas.yview(*args)

    def _on_wheel(self, event):
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")

    # ------------------------------------------------------------ 数据
    def set_rows(self, rows):
        """rows: [{ 'values': {col_id: text}, 'disabled': bool }]"""
        for w in self.body.winfo_children():
            w.destroy()
        self._rows = []
        self._selected = None
        pad_y = max(3, (self.row_height - 20) // 2)
        for idx, row in enumerate(rows):
            values = row.get("values", {})
            disabled = bool(row.get("disabled"))
            base_bg = theme.ROW_ALT if (idx % 2) else theme.CARD
            fg = theme.MUTED if disabled else theme.TEXT
            cells = {}
            for gi, col in self._grid_cols:
                if col is None:
                    line = tk.Frame(self.body, width=1, background=theme.CELL_LINE)
                    line.grid(row=idx, column=gi, sticky="ns")
                    line.bind("<Button-1>", lambda e, i=idx: self._select(i))
                    line.bind("<Double-1>", lambda e, i=idx: self._activate(i))
                    continue
                lab = tk.Label(self.body, text=str(values.get(col["id"], "")),
                               width=1, background=base_bg, foreground=fg,
                               anchor=col.get("anchor", "w"),
                               font=col.get("font") or theme.font(10),
                               padx=8, pady=pad_y)
                lab.grid(row=idx, column=gi, sticky="nsew")
                lab.bind("<Button-1>", lambda e, i=idx: self._select(i))
                lab.bind("<Double-1>", lambda e, i=idx: self._activate(i))
                cells[col["id"]] = lab
            self._rows.append({"cells": cells, "base_bg": base_bg, "fg": fg})
        self.body.update_idletasks()
        self._on_body_configure()

    def set_cell(self, index, col_id, value):
        if 0 <= index < len(self._rows):
            lab = self._rows[index]["cells"].get(col_id)
            if lab is not None:
                lab.configure(text=str(value))

    def set_values(self, index, values):
        for col_id, val in values.items():
            self.set_cell(index, col_id, val)

    def clear(self):
        self.set_rows([])

    def row_count(self):
        return len(self._rows)

    def selected_index(self):
        return self._selected

    # ------------------------------------------------------------ 选择
    def _select(self, index):
        if self._selected is not None and self._selected < len(self._rows):
            self._paint(self._selected, False)
        self._selected = index
        self._paint(index, True)

    def _activate(self, index):
        self._select(index)
        if self.on_activate is not None:
            self.on_activate(index)

    def _paint(self, index, selected):
        row = self._rows[index]
        bg = theme.SEL_BG if selected else row["base_bg"]
        fg = theme.TEXT if selected else row["fg"]
        for lab in row["cells"].values():
            lab.configure(background=bg, foreground=fg)
