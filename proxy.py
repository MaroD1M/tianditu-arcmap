# -*- coding: utf-8 -*-
"""瓦片代理核心：上游连接池 + 天地图请求转发、密钥轮换与本地缓存。"""

import http.client
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from constants import IS_WINDOWS, LAYERS, SUBDOMAINS
from http_server import ProxyHTTPServer
from utils import (app_base_dir, build_upstream_query, human_size,
                   parse_qs_ci, qget)


class ConnPool:
    """按 (scheme, host) 复用 HTTP 连接的简易连接池。

    天地图瓦片请求量很大，每次重建 TCP（https 还要 TLS 握手）非常慢，
    复用连接可显著加快出图速度。
    """

    MAX_FREE_PER_HOST = 8

    def __init__(self):
        self._free = {}
        self._lock = threading.Lock()

    def acquire(self, scheme, host, timeout=30):
        key = (scheme, host)
        with self._lock:
            lst = self._free.get(key)
            if lst:
                return lst.pop()
        cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        return cls(host, timeout=timeout)

    def release(self, scheme, host, conn):
        key = (scheme, host)
        with self._lock:
            lst = self._free.setdefault(key, [])
            if len(lst) < self.MAX_FREE_PER_HOST:
                lst.append(conn)
                return
        self._close(conn)

    @staticmethod
    def _close(conn):
        try:
            conn.close()
        except Exception:
            pass

    def close_all(self):
        with self._lock:
            pool, self._free = self._free, {}
        for lst in pool.values():
            for c in lst:
                self._close(c)


class TileProxy:
    """本地瓦片代理：把 http://localhost:port/wmts/<layer> 转发到天地图。"""

    def __init__(self, config, log_callback=None):
        self.config = config
        self.log_callback = log_callback
        self.lock = threading.RLock()
        self.mem_cache = {}
        self.pool = ConnPool()
        self.verbose = bool(config.get("verbose_log", False))
        self._server = None
        self._thread = None
        self._subdomain_idx = 0
        self.stats = {"total": 0, "tile": 0, "cache_hit": 0, "error": 0, "cap": 0}
        self.request_kinds = {}     # 请求类型明细：{"GETTILE": 12, "GETCAPABILITIES": 3, ...}
        self.samples = []           # 最近若干条原始请求样本（排障用）
        self.sample_limit = 60
        self.last_tile = ""         # 最近一次瓦片请求的坐标（排障用）
        self.cache_written = 0      # 本次运行写入磁盘的瓦片数
        self.cache_bytes = 0        # 本次运行写入的字节数
        self.cache_errors = 0       # 磁盘写入失败次数
        self._reset_usage()

    # ---- 生命周期 ----------------------------------------------------------
    def _reset_usage(self):
        for t in self.config.get("tokens", []):
            t["used"] = 0

    def start(self):
        if self._server is not None:
            return False
        self._reset_usage()
        self.reset_stats()
        port = int(self.config.get("port", 80) or 80)
        # 默认只监听本机：避免同一局域网内其他人借用你的密钥刷天地图配额。
        # 需要给别的机器用时，可在配置里把 local_only 设为 False。
        local_only = bool(self.config.get("local_only", True))
        bind_addr = "127.0.0.1" if local_only else "0.0.0.0"
        server = ProxyHTTPServer((bind_addr, port), self)
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        self.log("代理服务已启动：http://localhost:%d/（%s）"
                 % (port, "仅本机可访问" if local_only else "允许局域网访问"))
        return True

    def stop(self):
        if self._server is not None:
            server, self._server = self._server, None
            try:
                server.shutdown()      # 停止 accept 循环
            except Exception:
                pass
            try:
                n = server.shutdown_all_conns()   # 主动断开连接，避免干等
            except Exception:
                n = 0
            try:
                server.server_close()  # 内部不再阻塞等待线程池
            except Exception:
                pass
            self.pool.close_all()
            self.log("代理服务已停止" + ("（断开 %d 个连接）" % n if n else ""))
            return True
        return False

    def is_running(self):
        return self._server is not None

    @property
    def port(self):
        return int(self.config.get("port", 80) or 80)

    def reset_stats(self):
        with self.lock:
            for k in self.stats:
                self.stats[k] = 0
            self.request_kinds = {}
            self.samples = []
            self.last_tile = ""

    def record_sample(self, path, query):
        """记录一条原始请求样本，用于排查 ArcMap 到底怎么发请求。

        只保留前若干条 + 每种形态各留一条，避免刷爆内存。
        """
        shape = re.sub(r"\d+", "N", path)        # 把数字归一化，便于归并同类
        entry = "%s%s" % (path, ("?" + query) if query else "")
        with self.lock:
            if len(self.samples) >= self.sample_limit:
                return
            # 同形态的只留一条，不同形态都留
            if any(re.sub(r"\d+", "N", s.split("?")[0]) == shape for s in self.samples):
                return
            self.samples.append(entry)

    def get_stats(self):
        with self.lock:
            return dict(self.stats)

    def _bump(self, key, n=1):
        with self.lock:
            self.stats[key] = self.stats.get(key, 0) + n

    def _note_kind(self, kind):
        """记录请求类型明细，用于排障（ArcMap 到底发了哪些请求）。"""
        with self.lock:
            self.request_kinds[kind] = self.request_kinds.get(kind, 0) + 1

    # ---- 日志 --------------------------------------------------------------
    def log(self, msg):
        if self.log_callback:
            try:
                self.log_callback(msg)
            except Exception:
                pass

    # ---- 密钥选择（优先用用量最低、且未超额的密钥）------------------------
    def get_active_token(self):
        with self.lock:
            active = [t for t in self.config.get("tokens", []) if t.get("active")]
            if not active:
                return None
            under = [t for t in active if t.get("limit", 0) <= 0
                     or t.get("used", 0) < t.get("limit", 0)]
            pool = under or active
            pool = sorted(pool, key=lambda t: t.get("used", 0))
            return pool[0]

    def count_token(self, token):
        with self.lock:
            token["used"] = token.get("used", 0) + 1

    # ---- 子域轮换 ----------------------------------------------------------
    def next_subdomain(self):
        with self.lock:
            s = SUBDOMAINS[self._subdomain_idx % len(SUBDOMAINS)]
            self._subdomain_idx += 1
            return s

    # ---- 缓存 --------------------------------------------------------------
    def _cache_key(self, layer, qs):
        return (layer,
                qget(qs, "TILEMATRIX"),
                qget(qs, "TILEROW"),
                qget(qs, "TILECOL"))

    def cache_dir_path(self):
        """缓存目录的**绝对路径**（相对路径按程序所在目录解析）。"""
        base = self.config.get("cache_dir", "cache") or "cache"
        if not os.path.isabs(base):
            base = os.path.join(app_base_dir(), base)
        return os.path.abspath(base)

    def cache_dir_status(self):
        """检查缓存目录是否真的可写。返回 (绝对路径, 是否可写, 错误说明)。"""
        path = self.cache_dir_path()
        # 安全校验：拒绝明显危险的目录，避免误删程序自身或系统文件
        danger = self.cache_dir_danger(path)
        if danger:
            return path, False, danger
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".write_test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return path, True, ""
        except Exception as e:
            return path, False, str(e)

    @staticmethod
    def cache_dir_danger(path):
        """检查缓存目录是否危险（会误删重要文件），危险时返回原因，否则 None。"""
        try:
            p = os.path.abspath(path)
        except Exception:
            return "路径无效"
        base = os.path.abspath(app_base_dir())
        # 1) 不能是程序所在目录本身（否则清理会删掉源码/exe）
        if p == base:
            return "不能把缓存目录设为程序所在目录（清理时会误删程序文件）"
        # 2) 不能是盘符根目录
        drive, tail = os.path.splitdrive(p)
        if tail in ("\\", "/", ""):
            return "不能把缓存目录设为磁盘根目录"
        # 3) 不能是系统关键目录
        if IS_WINDOWS:
            sysroot = os.environ.get("SystemRoot", r"C:\Windows")
            for bad in (sysroot, os.path.join(sysroot, "System32"),
                        os.environ.get("ProgramFiles", r"C:\Program Files")):
                if bad and p.lower().rstrip("\\/") == os.path.abspath(bad).lower().rstrip("\\/"):
                    return "不能把缓存目录设为系统目录"
        else:
            for bad in ("/", "/etc", "/usr", "/bin", "/boot", "/dev", "/proc", "/sys"):
                if p.rstrip("/") == bad:
                    return "不能把缓存目录设为系统目录"
        # 4) 不能是程序目录的上级（可能删到程序目录）
        if base.startswith(p + os.sep):
            return "范围太大（包含程序目录），请选一个专门的子目录"
        return None

    def _is_tile_file(self, name):
        """判断是否为瓦片文件（排除 .ctype 之类的辅助文件）。"""
        if name.endswith(".ctype"):
            return False
        ext = os.path.splitext(name)[1].lower()
        return ext in self.EXT_CTYPE or ext == self.LEGACY_EXT

    def scan_cache(self):
        """统计缓存目录里的瓦片数量与总大小。返回 (张数, 字节数)。"""
        root_dir = self.cache_dir_path()
        count = total = 0
        try:
            for root, _dirs, files in os.walk(root_dir):
                for f in files:
                    if self._is_tile_file(f):
                        count += 1
                        try:
                            total += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass
        except Exception:
            pass
        return count, total

    # ---- 缓存清理 ----------------------------------------------------------
    def cache_limits(self):
        """读取缓存清理设置，返回 (体积上限MB, 过期天数)。0 表示不限制。"""
        try:
            mb = int(self.config.get("cache_max_mb", 0) or 0)
        except (TypeError, ValueError):
            mb = 0
        try:
            days = int(self.config.get("cache_expire_days", 0) or 0)
        except (TypeError, ValueError):
            days = 0
        return max(0, mb), max(0, days)

    def _iter_tile_files(self):
        """遍历所有瓦片文件，返回 [(路径, 大小, mtime)]（同时含 .ctype）。"""
        root_dir = self.cache_dir_path()
        items = []
        try:
            for root, _dirs, files in os.walk(root_dir):
                for f in files:
                    p = os.path.join(root, f)
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    is_tile = self._is_tile_file(f)
                    items.append((p, st.st_size, st.st_mtime, is_tile))
        except Exception:
            pass
        return items

    def clean_cache(self):
        """按体积上限 / 过期天数清理缓存。返回统计字典。

        策略：
          1) 先删过期（mtime 早于 N 天）的瓦片；
          2) 若仍超过体积上限，按 mtime 从旧到新继续删，直到低于上限。
        .ctype 辅助文件跟随其瓦片一起删除。
        """
        max_mb, days = self.cache_limits()
        result = {"expired": 0, "size_trimmed": 0, "freed": 0,
                  "files": 0, "kept_mb": 0.0, "skipped": False}
        if max_mb <= 0 and days <= 0:
            result["skipped"] = True
            n, total = self.scan_cache()
            result["kept_mb"] = round(total / 1048576.0, 2)
            result["files"] = n
            return result

        items = self._iter_tile_files()
        if not items:
            return result

        tiles = [it for it in items if it[3]]
        aux = {it[0] for it in items if not it[3]}      # .ctype 文件路径集合

        def _remove(path, is_tile):
            removed = 0
            for q in (path, path + ".ctype"):
                try:
                    if os.path.exists(q):
                        removed += os.path.getsize(q)
                        os.remove(q)
                except OSError:
                    pass
            return removed

        now = time.time()
        remaining = []
        # 1) 过期清理
        if days > 0:
            cutoff = now - days * 86400
            for p, size, mtime, _ in tiles:
                if mtime < cutoff:
                    result["freed"] += _remove(p, True)
                    result["expired"] += 1
                else:
                    remaining.append((p, size, mtime))
        else:
            remaining = [(p, s, m) for p, s, m, _ in tiles]

        # 2) 体积清理（从最旧开始删）
        if max_mb > 0:
            limit = max_mb * 1048576
            total = sum(s for _p, s, _m in remaining)
            if total > limit:
                remaining.sort(key=lambda x: x[2])      # 旧的在前
                idx = 0
                while total > limit and idx < len(remaining):
                    p, size, _m = remaining[idx]
                    removed = _remove(p, True)
                    total -= size
                    result["freed"] += max(removed, size)
                    result["size_trimmed"] += 1
                    idx += 1
                remaining = remaining[idx:]

        # 3) 清掉可能残留的孤儿 .ctype
        for q in list(aux):
            if not os.path.exists(q.rsplit(".ctype", 1)[0]):
                try:
                    os.remove(q)
                except OSError:
                    pass

        result["files"] = len(remaining)
        result["kept_mb"] = round(sum(s for _p, s, _m in remaining) / 1048576.0, 2)
        return result

    def clear_all_cache(self, only_known_layers=True):
        """删除缓存内容，返回释放的字节数。

        安全要点：**只删本程序自己生成的瓦片文件**，绝不无差别清空目录。
        因为用户可能把缓存目录设成已有数据的目录（甚至程序目录），
        无差别删除会误删用户的文件。

        only_known_layers=True 时只处理「已知图层名」目录下的瓦片；
        这样可以确保删掉的一定是本程序写出来的东西。
        """
        root_dir = self.cache_dir_path()
        if not os.path.isdir(root_dir):
            return 0
        freed = 0
        removed_dirs = set()

        # 逐个删除瓦片文件（含其 .ctype），只认我们自己生成的文件名规则
        for p, size, _m, is_tile in self._iter_tile_files():
            if only_known_layers:
                # 校验：路径里必须包含一层已知图层名，否则跳过（不是我们的文件）
                rel = os.path.relpath(p, root_dir).replace("\\", "/")
                parts = rel.split("/")
                if not any(seg in LAYERS for seg in parts):
                    continue
            try:
                os.remove(p)
                freed += size
                removed_dirs.add(os.path.dirname(p))
            except OSError:
                pass

        # 清理空的图层/级别/行目录（只删空目录，遇到非空立即停止，不碰用户文件）
        def prune(d):
            try:
                entries = os.listdir(d)
            except OSError:
                return
            for e in entries:
                sub = os.path.join(d, e)
                if os.path.isdir(sub):
                    prune(sub)
            try:
                if not os.listdir(d) and os.path.abspath(d) != os.path.abspath(root_dir):
                    os.rmdir(d)
            except OSError:
                pass

        prune(root_dir)

        with self.lock:
            self.mem_cache.clear()
        return freed

    def cache_diagnose(self):
        """缓存诊断：给出「为什么不缓存」的明确答案。

        返回 (是否正常, 说明文字)。用于界面上直接告诉用户原因。
        """
        if not self.config.get("cache_enabled"):
            return False, "未启用「本地缓存」勾选"
        path, ok, err = self.cache_dir_status()
        if not ok:
            return False, "缓存目录不可写：%s" % err
        n, total = self.scan_cache()
        if self.cache_errors:
            return False, ("磁盘写入失败 %d 次（目录：%s）"
                           % (self.cache_errors, path))
        with self.lock:
            kinds = dict(self.request_kinds)
            tile_cnt = self.stats.get("tile", 0)
        if tile_cnt == 0 and n == 0:
            if kinds:
                detail = "、".join("%s×%d" % (k, v) for k, v in
                                   sorted(kinds.items(), key=lambda x: -x[1])[:5])
                return False, ("还没有瓦片请求。当前收到的请求类型：%s" % detail)
            return False, "本次运行还没有任何请求（ArcMap 未连接过？）"
        return True, "正常"

    def cache_report(self):
        """缓存诊断的详细报告（多行），用于弹窗展示。"""
        n, total = self.scan_cache()
        ok, why = self.cache_diagnose()
        with self.lock:
            kinds = dict(self.request_kinds)
            last = self.last_tile
            samples = list(self.samples)
        kind_txt = "、".join("%s × %d" % (k, v) for k, v in
                            sorted(kinds.items(), key=lambda x: -x[1])) or "（无）"
        lines = [
            "缓存目录：%s" % self.cache_dir_path(),
            "",
            "磁盘上已有瓦片：%d 张" % n,
            "占用空间：%s" % human_size(total),
            "本次运行新写入：%d 张 / %s" % (self.cache_written,
                                            human_size(self.cache_bytes)),
            "写入失败：%d 次" % self.cache_errors,
            "",
            "收到请求类型：%s" % kind_txt,
            "最近瓦片请求：%s" % (last or "（无）"),
            "",
            "状态：%s" % why,
        ]
        if samples:
            lines += ["", "原始请求样本（最多 %d 条）：" % len(samples)]
            lines += ["  " + s for s in samples]
        return "\n".join(lines)

    # ---- 缓存文件命名 ------------------------------------------------------
    # 常见图片类型 -> 扩展名
    CTYPE_EXT = {
        "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/pjpeg": ".jpg",
        "image/png": ".png", "image/gif": ".gif",
        "image/bmp": ".bmp", "image/webp": ".webp",
        "image/tiff": ".tif",
    }
    # 扩展名 -> Content-Type（读取时反查）
    EXT_CTYPE = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".bmp": "image/bmp", ".webp": "image/webp", ".tif": "image/tiff",
        ".tile": "image/jpeg",       # 兼容旧版本缓存
        ".bin": "application/octet-stream",
    }
    # 旧版本用的统一后缀（仍需能读）
    LEGACY_EXT = ".tile"

    @classmethod
    def ext_for_ctype(cls, ctype):
        """根据 Content-Type 决定缓存文件扩展名。"""
        base = (ctype or "").split(";")[0].strip().lower()
        return cls.CTYPE_EXT.get(base, ".bin")

    @classmethod
    def ctype_for_ext(cls, ext):
        """根据扩展名反查 Content-Type。"""
        return cls.EXT_CTYPE.get((ext or "").lower(), "application/octet-stream")

    def _tile_dir(self, layer, z, y):
        safe = lambda v: re.sub(r"[^A-Za-z0-9_\-]", "", str(v))
        return os.path.join(self.cache_dir_path(), safe(layer), safe(z), safe(y))

    def _disk_path(self, layer, z, y, x, ext=None):
        """缓存文件路径。ext 为空时用旧版统一后缀（仅供兼容/占位）。"""
        safe = lambda v: re.sub(r"[^A-Za-z0-9_\-]", "", str(v))
        return os.path.join(self._tile_dir(layer, z, y),
                            safe(x) + (ext or self.LEGACY_EXT))

    def _find_cached_file(self, layer, z, y, x):
        """查找某个瓦片已存在的缓存文件（不依赖具体扩展名）。

        因为写入时才根据 Content-Type 决定扩展名，读取时必须按名字前缀
        去匹配，才能同时兼容 .jpg/.png 和旧版的 .tile。
        """
        safe = lambda v: re.sub(r"[^A-Za-z0-9_\-]", "", str(v))
        stem = safe(x)
        d = self._tile_dir(layer, z, y)
        try:
            for name in os.listdir(d):
                if name.startswith(stem + ".") and not name.endswith(".ctype"):
                    return os.path.join(d, name)
        except OSError:
            pass
        return None

    def get_cached(self, layer, qs):
        """命中返回 (data:bytes, content_type:str)，否则 None。"""
        key = self._cache_key(layer, qs)
        with self.lock:
            if key in self.mem_cache:
                return self.mem_cache[key]
        if self.config.get("cache_enabled"):
            try:
                p = self._find_cached_file(layer, *key[1:])
                if p:
                    with open(p, "rb") as f:
                        data = f.read()
                    # 类型优先取同目录的 .ctype（更可靠），否则按扩展名反查
                    ctype = None
                    cp = p + ".ctype"
                    if os.path.exists(cp):
                        with open(cp, "r", encoding="utf-8") as f:
                            ctype = f.read().strip() or None
                    if not ctype:
                        ctype = self.ctype_for_ext(os.path.splitext(p)[1])
                    with self.lock:
                        self._put_mem(key, data, ctype)
                    return (data, ctype)
            except Exception:
                pass
        return None

    def invalidate_mem_cache(self, reason=""):
        """清空内存缓存。

        切换缓存目录 / 开关缓存时必须调用：否则旧目录写入的瓦片仍在内存里命中，
        新目录永远收不到数据，看起来就像「缓存不生效」。
        """
        with self.lock:
            n = len(self.mem_cache)
            self.mem_cache.clear()
        if n and reason:
            self.log("[缓存] 已清空内存缓存（%d 张）%s" % (n, reason))
        return n

    def set_cached(self, layer, qs, data, ctype):
        key = self._cache_key(layer, qs)
        with self.lock:
            self._put_mem(key, data, ctype)
        if not self.config.get("cache_enabled"):
            return
        try:
            # 按真实类型存扩展名，例如 .jpg / .png
            p = self._disk_path(layer, *key[1:], ext=self.ext_for_ctype(ctype))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
            # 同时写 .ctype 作为类型兜底（扩展名推断不到时用）
            if ctype:
                with open(p + ".ctype", "w", encoding="utf-8") as f:
                    f.write(ctype)
            with self.lock:
                self.cache_written += 1
                self.cache_bytes += len(data)
        except Exception as e:
            with self.lock:
                self.cache_errors += 1
                first = self.cache_errors == 1
            if first:
                # 只提示第一次，避免刷屏；这样缓存写不进去时用户能立刻发现
                self.log("[缓存] ❌ 写入磁盘失败，缓存不会生效：%s\n"
                         "        缓存目录：%s\n"
                         "        请在「服务与地址」里点「浏览」换一个可写的目录。"
                         % (e, self.cache_dir_path()))

    def _put_mem(self, key, data, ctype):
        if len(self.mem_cache) >= 5000:
            for k in list(self.mem_cache)[: 2500]:
                self.mem_cache.pop(k, None)
        self.mem_cache[key] = (data, ctype)

    # ---- 能力文档改写（让 ArcMap 的瓦片请求走本地代理）-------------------
    def rewrite_capabilities(self, body):
        if isinstance(body, bytes):
            text = body.decode("utf-8", errors="replace")
        else:
            text = str(body)
        port = self.port
        local = "localhost:%d" % port if port != 80 else "localhost"
        text = re.sub(r"\bt[0-7]\.tianditu\.gov\.cn\b", local, text)
        return text.encode("utf-8")

    # ---- 上游请求（走连接池）----------------------------------------------
    def _fetch_upstream(self, scheme, host, path, timeout=30):
        """返回 (status, content_type, body)。失败抛异常。"""
        last_err = None
        for attempt in (0, 1):
            conn = self.pool.acquire(scheme, host, timeout)
            try:
                conn.request("GET", path)
                resp = conn.getresponse()
                body = resp.read()
                status = resp.status
                ctype = resp.getheader("Content-Type", "application/octet-stream")
                if resp.will_close:
                    ConnPool._close(conn)
                else:
                    self.pool.release(scheme, host, conn)
                return status, ctype, body
            except Exception as e:
                ConnPool._close(conn)
                last_err = e
                if attempt == 1:
                    raise
        raise last_err if last_err else RuntimeError("unknown")

    # ---- 核心转发 ----------------------------------------------------------
    def handle_request(self, path, query):
        """返回 (status:int, content_type:str, body:bytes)。"""
        self._bump("total")
        self.record_sample(path, query)

        segments = [s for s in path.strip("/").split("/") if s]
        layer, rest = None, []
        for i, seg in enumerate(segments):
            if seg in LAYERS:
                layer, rest = seg, segments[i + 1:]
                break
        if layer is None:
            self._bump("error")
            return 404, "text/plain; charset=utf-8", \
                ("未知图层。可用图层：%s" % ", ".join(sorted(LAYERS))).encode("utf-8")

        qs = parse_qs_ci(query)
        request_type = qget(qs, "REQUEST").upper()

        # ArcMap 会试探 REST 风格能力文档地址（如 /1.0.0/WMTSCapabilities.xml）
        rest_lower = "/".join(rest).lower()
        if "wmtscapabilities" in rest_lower or "capabilities" in rest_lower:
            request_type = "GETCAPABILITIES"

        # 记录请求类型明细：排障时能一眼看出 ArcMap 到底发了什么
        kind = request_type or ("(无REQUEST参数)" if not rest else "/".join(rest))
        self._note_kind(kind)
        # 瓦片类请求（含没有 REQUEST 参数但带 TILEMATRIX 的写法）也要能缓存
        is_tile_req = (request_type == "GETTILE"
                       or all(k in qs for k in ("TILEMATRIX", "TILEROW", "TILECOL")))
        if is_tile_req:
            self.last_tile = "%s z=%s row=%s col=%s" % (
                layer, qget(qs, "TILEMATRIX"),
                qget(qs, "TILEROW"), qget(qs, "TILECOL"))

        mode = self.config.get("mode", "esri")
        # 上游子路径：
        #   GetCapabilities -> esri 接口（分辨率修正为 EPSG:3857，避免偏移）
        #   GetTile         -> 标准 wmts 接口（esri 接口只出能力文档、不提供瓦片）
        if is_tile_req:
            upstream_suffix = "wmts"
        elif request_type == "GETCAPABILITIES":
            upstream_suffix = "esri/wmts" if mode == "esri" else "wmts"
            # 强制用规范的 KVP 参数（兼容 REST 风格、WMS 探测等请求）
            qs = parse_qs_ci("SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0")
        elif rest:
            upstream_suffix = "/".join(rest)
        else:
            upstream_suffix = "esri/wmts" if mode == "esri" else "wmts"

        # 密钥注入（覆盖客户端携带的 tk，实现多密钥轮换）
        token = self.get_active_token()
        if token is None:
            self._bump("error")
            return 403, "text/plain; charset=utf-8", \
                "没有可用的天地图密钥，请先在界面中添加并启用密钥。".encode("utf-8")

        # 瓦片缓存命中
        if is_tile_req and self.config.get("cache_enabled"):
            cached = self.get_cached(layer, qs)
            if cached is not None:
                data, ctype = cached
                self._bump("tile")
                self._bump("cache_hit")
                if self.verbose:
                    self.log("[缓存命中] %s z=%s row=%s col=%s（%d 字节）" % (
                        layer, qget(qs, "TILEMATRIX"),
                        qget(qs, "TILEROW"), qget(qs, "TILECOL"),
                        len(data)))
                return 200, ctype, data

        sub = self.next_subdomain()
        scheme = self.config.get("scheme", "http")
        host = "%s.tianditu.gov.cn" % sub
        # 保留客户端原始的 key 大小写，并注入我们选的 tk
        new_query = build_upstream_query(qs, extra=[("tk", token.get("token", ""))])
        upstream_path = "/%s/%s?%s" % (layer, upstream_suffix, new_query)

        # 注意：不要自定义 User-Agent/Referer，否则会被天地图 WAF 拦截返回 403
        try:
            status, content_type, body = self._fetch_upstream(scheme, host, upstream_path)
        except urllib.error.HTTPError as e:
            self._bump("error")
            self.log("[错误] 天地图返回 HTTP %s（%s/%s）" % (e.code, layer, upstream_suffix))
            return e.code, "text/plain; charset=utf-8", \
                ("上游返回 HTTP %s" % e.code).encode("utf-8")
        except Exception as e:
            self._bump("error")
            self.log("[错误] 请求天地图失败：%s" % e)
            return 502, "text/plain; charset=utf-8", \
                ("请求天地图失败：%s" % e).encode("utf-8")

        if request_type == "GETCAPABILITIES":
            body = self.rewrite_capabilities(body)
            content_type = "application/xml; charset=utf-8"
            self._bump("cap")
            self.log("[能力文档] %s（%d 字节）" % (layer, len(body)))
        elif is_tile_req:
            self.set_cached(layer, qs, body, content_type)
            self.count_token(token)
            self._bump("tile")
            if self.verbose:
                self.log("[瓦片] %s %s/%s/%s（%d 字节）" % (layer,
                    qget(qs, "TILEMATRIX"), qget(qs, "TILEROW"),
                    qget(qs, "TILECOL"), len(body)))

        return status, content_type, body

    # ---- 密钥有效性测试 ----------------------------------------------------
    def test_token(self, token, layer="img_w"):
        """用一张真实瓦片验证密钥是否可用。返回 (是否有效, 说明)。"""
        qs = urllib.parse.urlencode({
            "SERVICE": "WMTS", "REQUEST": "GetTile", "VERSION": "1.0.0",
            "LAYER": "img", "STYLE": "default", "TILEMATRIXSET": "w",
            "FORMAT": "tiles", "TILEMATRIX": "3", "TILEROW": "2", "TILECOL": "3",
            "tk": token,
        })
        url = "http://t0.tianditu.gov.cn/img_w/wmts?" + qs
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = resp.read(4)
                if resp.status == 200 and data[:2] == b"\xff\xd8":
                    return True, "有效（返回正常瓦片）"
                return False, "返回异常内容，疑似密钥类型不对"
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False, "HTTP %s：密钥无效或当日额度已用尽" % e.code
            return False, "HTTP %s" % e.code
        except Exception as e:
            return False, "网络错误：%s" % e
