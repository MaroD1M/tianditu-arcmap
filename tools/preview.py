#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成界面预览图（开发用）。

在无显示器的 Linux 上用 Xvfb 跑起图形界面，逐个页签截图，并拼成一张大图，
便于审查界面细节、发现需要优化的地方。

依赖（仅开发时需要，运行程序本身不需要）：
    python3-tk            图形界面
    中文字体               如 fonts-wqy-microhei（否则中文显示为方块）
    Xvfb                  虚拟显示（已有 DISPLAY 时可不装）
    ImageMagick (import)  截图；没有时在 Windows 上回退到 Pillow ImageGrab
    Pillow                裁切与拼图（pip install pillow）

用法：
    python tools/preview.py                     # 默认 1.6 倍，输出到 preview/
    python tools/preview.py --scale 2.0         # 更大更清晰（注意绘制时间与体积）
    python tools/preview.py --outdir D:/预览     # 指定输出目录
    python tools/preview.py --no-proxy          # 不启动代理（显示"已停止"状态）

说明：
    * 会注入一组示例密钥/底图，不会读写仓库里的 config.json；
    * 缓存目录使用临时目录，不会污染仓库；
    * 生成的文件：
        preview/01_服务与地址.png
        preview/02_密钥管理.png
        preview/03_底图选择.png
        preview/04_运行日志.png
        preview/界面预览_v2.png        <- 2x2 拼图
"""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BASE_W, BASE_H = 980, 730          # App 在 1.0 倍时的默认窗口尺寸
TABS = [(0, "服务与地址"), (1, "密钥管理"), (2, "底图选择"), (3, "运行日志")]

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
]


def have(cmd):
    return shutil.which(cmd) is not None


def load_font(size):
    from PIL import ImageFont
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def start_xvfb(scale):
    """没有 DISPLAY 时启动 Xvfb，返回 (进程, 是否由本脚本启动)。"""
    if os.environ.get("DISPLAY"):
        return None, False
    if not have("Xvfb"):
        sys.exit("错误：没有 DISPLAY，且未安装 Xvfb。\n"
                 "  Debian/Ubuntu: sudo apt install xvfb\n"
                 "  或先在有图形界面的环境运行。")
    w = int(BASE_W * scale) + 160
    h = int(BASE_H * scale) + 200
    for num in range(99, 120):
        disp = ":%d" % num
        if os.path.exists("/tmp/.X11-unix/X%d" % num):
            continue
        proc = subprocess.Popen(
            ["Xvfb", disp, "-screen", "0", "%dx%dx24" % (w, h)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        if proc.poll() is None:
            os.environ["DISPLAY"] = disp
            return proc, True
    sys.exit("错误：无法启动 Xvfb（找不到可用显示号）。")


def sample_config(port, cache_dir):
    return {
        "port": port,
        "scheme": "http",
        "mode": "esri",
        "local_only": True,
        "cache_enabled": True,
        "cache_dir": cache_dir,
        "cache_max_mb": 1024,
        "cache_expire_days": 30,
        "layers": ["img_w", "img_c", "vec_w", "vec_c"],
        "tokens": [
            {"token": "0a1b2c3d4e5f60718293a4b5c6d7e8f9", "active": True,
             "limit": 10000, "description": "主账号", "used": 1234},
            {"token": "ffeeddccbbaa99887766554433221100", "active": False,
             "limit": 10000, "description": "备用", "used": 0},
        ],
        "close_to_tray": False,
        "autostart": False,
        "geometry": "",
        "verbose_log": False,
    }


def build_app(scale, port, cache_dir):
    import gui

    cfg = sample_config(port, cache_dir)
    # 覆盖配置读写，避免动到仓库里的 config.json
    gui.load_config = lambda *a, **k: dict(cfg)
    gui.save_config = lambda *a, **k: None

    # 放大界面：Tk 的 scaling 让字号按比例变大，窗口尺寸同步放大
    def scaled(self):
        if scale != 1.0:
            try:
                self.tk.call("tk", "scaling", float(scale))
            except Exception:
                pass
        return float(scale)

    gui.App._apply_dpi_scaling = scaled
    return gui.App()


def capture(app, path):
    """截取主窗口并保存到 path，返回窗口尺寸。

    优先按窗口 ID 截图（尺寸精确、不受窗口在屏幕上的位置影响）；
    没有 ImageMagick 时在 Windows 上回退到 Pillow ImageGrab。
    """
    app.update_idletasks()
    app.update()
    w, h = app.winfo_width(), app.winfo_height()
    if have("import"):
        subprocess.run(["import", "-window", hex(app.winfo_id()), path], check=True)
    else:
        from PIL import ImageGrab
        x, y = app.winfo_rootx(), app.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)
    return w, h


def make_collage(tiles, out_path, scale):
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert("RGB") for p in tiles]
    w, h = ims[0].size
    gap = max(16, int(24 * scale))
    pad = max(16, int(24 * scale))
    top = max(44, int(52 * scale))
    W = pad * 2 + w * 2 + gap
    H = pad + top + h * 2 + gap + pad
    sheet = Image.new("RGB", (W, H), (238, 242, 247))
    d = ImageDraw.Draw(sheet)
    title = "天地图 ArcMap 加载工具 v2 · 界面预览（服务与地址 / 密钥管理 / 底图选择 / 运行日志）"
    d.text((pad, int(pad * 0.5)), title, fill=(47, 111, 191),
           font=load_font(max(16, int(24 * scale))))
    for i, im in enumerate(ims):
        r, c = divmod(i, 2)
        x = pad + c * (w + gap)
        y = pad + top + r * (h + gap)
        d.rectangle([x - 1, y - 1, x + w + 1, y + h + 1],
                    fill=(255, 255, 255), outline=(198, 208, 224))
        sheet.paste(im, (x, y))
    sheet.save(out_path)
    return sheet.size


def main():
    ap = argparse.ArgumentParser(description="生成天地图加载工具的界面预览图")
    ap.add_argument("--scale", type=float, default=1.6,
                    help="界面放大倍数（默认 1.6；2.0 更大更清晰）")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "preview"),
                    help="输出目录（默认 <仓库>/preview）")
    ap.add_argument("--port", type=int, default=0,
                    help="示例服务端口（默认自动选择空闲端口）")
    ap.add_argument("--no-proxy", action="store_true",
                    help="不启动代理，界面显示「已停止」状态")
    args = ap.parse_args()

    if importlib.util.find_spec("PIL") is None:
        sys.exit("缺少 Pillow，请先安装：pip install pillow")
    if importlib.util.find_spec("tkinter") is None:
        sys.exit("缺少 tkinter。\n"
                 "  Debian/Ubuntu: sudo apt install python3-tk\n"
                 "  Windows/macOS: 官方 Python 安装包已自带")

    if args.scale < 1.0 or args.scale > 4.0:
        sys.exit("--scale 建议在 1.0 ~ 4.0 之间")

    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)
    cache_dir = tempfile.mkdtemp(prefix="tdt_preview_cache_")

    xvfb, own_xvfb = start_xvfb(args.scale)

    import utils
    port = args.port or utils.find_free_port(
        candidates=(18999, 18080, 12303, 8080)) or 18888

    app = None
    tile_paths = []
    try:
        app = build_app(args.scale, port, cache_dir)

        def run():
            for msg in [
                "提示：先在「密钥管理」添加天地图密钥，再点「启动服务」。",
                "首次使用请点菜单「帮助 → 使用步骤」，内含申请密钥的完整指引。",
            ]:
                app._push_ui_log(msg)
            if not args.no_proxy:
                try:
                    app.proxy.start()
                    app._push_ui_log("代理服务已启动：http://localhost:%d/（仅本机可访问）" % port)
                except Exception as e:
                    app._push_ui_log("代理启动失败：%s" % e)
            app._update_server_state()
            app._drain_log()

            idx = {"i": 0}

            def step():
                if idx["i"] >= len(TABS):
                    finish()
                    return
                tab_idx, name = TABS[idx["i"]]
                idx["i"] += 1
                app.nb.select(tab_idx)
                app.update_idletasks()
                app.update()
                app.after(300, lambda: do_shot(tab_idx, name))

            def do_shot(tab_idx, name):
                path = os.path.join(outdir, "%02d_%s.png" % (tab_idx + 1, name))
                size = capture(app, path)
                tile_paths.append(path)
                print("  已截图 %-14s %dx%d" % (name, size[0], size[1]))
                app.after(250, step)

            app.after(600, step)

        def finish():
            collage = os.path.join(outdir, "界面预览_v2.png")
            size = make_collage(tile_paths, collage, args.scale)
            print("拼图已生成：%s（%dx%d）" % (collage, size[0], size[1]))
            app.destroy()

        app.after(500, run)
        app.mainloop()
    finally:
        try:
            if app is not None:
                app.proxy.stop()
        except Exception:
            pass
        shutil.rmtree(cache_dir, ignore_errors=True)
        if own_xvfb and xvfb is not None:
            xvfb.terminate()
            try:
                xvfb.wait(timeout=3)
            except Exception:
                xvfb.kill()

    if not tile_paths:
        sys.exit("未生成任何截图，请检查上面的错误信息。")
    print("完成。")


if __name__ == "__main__":
    main()
