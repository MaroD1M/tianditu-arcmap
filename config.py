# -*- coding: utf-8 -*-
"""配置读写：加载 / 保存 config.json。"""

import json
import os

from constants import DEFAULT_CONFIG, DEFAULT_LAYERS, LAYERS
from utils import default_config_path


def load_config(path=None):
    """读取配置文件；不存在或损坏时返回默认配置。"""
    if path is None:
        path = default_config_path()
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in DEFAULT_CONFIG:
                    if k in data:
                        cfg[k] = data[k]
                # 兼容：旧配置里的单个 token 字段
                if not cfg["tokens"] and isinstance(data.get("token"), str) and data["token"]:
                    cfg["tokens"] = [{"token": data["token"], "active": True,
                                      "limit": 10000, "description": ""}]
                tokens = []
                for t in cfg["tokens"]:
                    if isinstance(t, dict) and t.get("token"):
                        tokens.append({
                            "token": str(t.get("token", "")).strip(),
                            "active": bool(t.get("active", True)),
                            "limit": int(t.get("limit", 10000) or 0),
                            "description": str(t.get("description", "")),
                        })
                cfg["tokens"] = tokens
                cfg["port"] = int(cfg.get("port", 80) or 80)
                cfg["layers"] = [l for l in cfg.get("layers", []) if l in LAYERS]
        except Exception as e:
            print("读取配置失败，使用默认配置：%s" % e)
    return cfg


def save_config(cfg, path=None):
    """保存配置（tokens 只保留持久化字段）。"""
    if path is None:
        path = default_config_path()
    data = {
        "port": cfg.get("port", 80),
        "scheme": cfg.get("scheme", "http"),
        "mode": cfg.get("mode", "esri"),
        "local_only": bool(cfg.get("local_only", True)),
        "cache_enabled": bool(cfg.get("cache_enabled", True)),
        "cache_dir": cfg.get("cache_dir", "cache"),
        "cache_max_mb": int(cfg.get("cache_max_mb", 1024) or 0),
        "cache_expire_days": int(cfg.get("cache_expire_days", 30) or 0),
        "layers": list(cfg.get("layers", DEFAULT_LAYERS)),
        "tokens": [{
            "token": t.get("token", ""),
            "active": bool(t.get("active", True)),
            "limit": int(t.get("limit", 0) or 0),
            "description": t.get("description", ""),
        } for t in cfg.get("tokens", [])],
        "close_to_tray": bool(cfg.get("close_to_tray", True)),
        "autostart": bool(cfg.get("autostart", False)),
        "geometry": cfg.get("geometry", ""),
        "verbose_log": bool(cfg.get("verbose_log", False)),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
