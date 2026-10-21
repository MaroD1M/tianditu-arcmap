# -*- coding: utf-8 -*-
"""本地 HTTP 服务：有界线程池 + 连接跟踪 + 请求处理器。"""

import socket
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from constants import DEFAULT_LAYERS, LAYERS


class ProxyHTTPServer(ThreadingHTTPServer):
    """带并发上限的线程化 HTTP 服务器（有界线程池，不阻塞 accept 循环）。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, proxy, max_workers=64):
        super().__init__(addr, ProxyHandler)
        self.proxy = proxy
        # 用有界线程池限制并发线程数，避免 ArcMap 并发请求时线程爆炸；
        # 超出上限的请求排队等待，不会阻塞 accept 循环。
        #
        # 注意：不要试图把 worker 改成 daemon 来「保证退出」。
        #   · Thread.start() 之后再设 daemon 会抛 RuntimeError，改不了；
        #   · concurrent.futures 的 atexit 钩子会无条件 join 所有 worker，
        #     daemon 属性也挡不住。
        # 退出安全由 TileProxy.stop()（断开在途上游连接）+ GUI 的
        # _force_exit()（兜底强制结束进程）共同保证。
        self._executor = ThreadPoolExecutor(max_workers=max_workers,
                                            thread_name_prefix="tile")
        # 记录所有活跃连接。停止时必须主动断开，否则要等 keep-alive
        # TCP 超时（最长 65 秒），表现为「点停止服务卡死」。
        self._conns = set()
        self._conns_lock = threading.Lock()

    def _track(self, request, add=True):
        with self._conns_lock:
            if add:
                self._conns.add(request)
            else:
                self._conns.discard(request)

    def shutdown_all_conns(self):
        """强制断开所有活跃连接（含空闲的 keep-alive 连接）。返回断开数量。"""
        with self._conns_lock:
            conns = list(self._conns)
            self._conns.clear()
        for c in conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                c.close()
            except Exception:
                pass
        return len(conns)

    def process_request(self, request, client_address):
        self._track(request, True)
        try:
            self._executor.submit(self._handle_one, request, client_address)
        except RuntimeError:
            # 线程池已关闭（正在退出），直接丢弃该请求
            self._track(request, False)
            self.shutdown_request(request)

    def _handle_one(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self._track(request, False)
            self.shutdown_request(request)

    def server_close(self):
        """关闭服务：立刻断开所有连接，线程池异步收尾（不阻塞调用方）。

        顺序很重要：
          1. 先断开活跃连接 —— 否则要等 keep-alive 超时（最长 65 秒）；
          2. shutdown(wait=False) —— 让正在处理的请求自己结束；
          3. 后台线程再等线程池退出，绝不阻塞 UI 线程。
        """
        try:
            self.shutdown_all_conns()
        except Exception:
            pass
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass
        except Exception:
            pass
        super().server_close()

    def wait_closed(self, timeout=5.0):
        """在后台等待线程池真正结束（供退出流程使用，必须不在 UI 线程调用）。"""
        try:
            ex = getattr(self, "_executor", None)
            if ex is None:
                return True
            t = threading.Thread(target=lambda: ex.shutdown(wait=True),
                                 daemon=True)
            t.start()
            t.join(timeout=timeout)
            return not t.is_alive()
        except Exception:
            return True


class ProxyHandler(BaseHTTPRequestHandler):
    server_version = "TiandituProxy/2.0"
    protocol_version = "HTTP/1.1"
    timeout = 20          # 空闲 keep-alive 超时；不宜过长，否则停止服务会等很久

    @property
    def proxy(self):
        return self.server.proxy

    def do_GET(self):
        self._serve(head_only=False)

    def do_HEAD(self):
        self._serve(head_only=True)

    def _serve(self, head_only):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path or "/"

        if path in ("/", "/index.html"):
            status, ctype, body = self._status_page()
        else:
            status, ctype, body = self.proxy.handle_request(path, parsed.query)

        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=86400")
            # 只允许本机页面跨域访问；默认关闭局域网暴露时不放开
            if not self.proxy.config.get("local_only", True):
                self.send_header("Access-Control-Allow-Origin", "*")
            else:
                self.send_header("Access-Control-Allow-Origin",
                                 "http://localhost:%d" % self.proxy.port)
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _status_page(self):
        """返回 (status, content_type, body)。"""
        layers = self.proxy.config.get("layers", DEFAULT_LAYERS)
        port = self.proxy.port
        rows = "".join(
            "<tr><td>%s</td><td>%s</td><td><a href=\"/wmts/%s\">/wmts/%s</a></td></tr>"
            % (l, LAYERS.get(l, l), l, l) for l in layers)
        html = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>天地图代理</title>
<style>body{font-family:"Microsoft YaHei",sans-serif;margin:32px}
table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px 12px}</style>
</head><body>
<h2>天地图 ArcMap 代理服务运行中</h2>
<p>在 ArcMap 中添加 WMTS 服务器，URL 填：<b>http://localhost:%d/wmts/&lt;图层&gt;</b></p>
<table><tr><th>图层</th><th>说明</th><th>地址</th></tr>%s</table>
</body></html>""" % (port, rows)
        return 200, "text/html; charset=utf-8", html.encode("utf-8")

    def log_message(self, fmt, *args):
        # 默认的逐请求日志会与瓦片日志一起刷屏，这里直接丢弃（统计走计数器）
        pass

    def log_error(self, fmt, *args):
        try:
            self.proxy.log("[提示] " + (fmt % args))
        except Exception:
            pass
