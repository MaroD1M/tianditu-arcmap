# -*- coding: utf-8 -*-
"""
天地图 ArcMap 加载工具（可视化版 · v2）
========================================

把「天地图」在线底图加载到 ArcMap 的图形化工具：

1. 可视化填写 / 管理多个天地图密钥（tk），自动生成并保存配置；
2. 一键启动本地瓦片代理服务器，把天地图底图转发给 ArcMap 使用；
3. 多密钥按配额轮换，支持本地缓存与自动清理，一键复制 ArcMap 连接地址；
4. 关闭窗口可最小化到系统托盘，后台继续提供瓦片服务；
5. 界面内置使用步骤与密钥申请指引，方便新手直接上手。

运行期仅依赖 Python 标准库（tkinter / http.server / http.client / json / ctypes），
无需任何第三方包；打包见同目录 build.bat。

说明：本工具不采集、不上传任何信息，密钥仅保存在本机配置文件。所有网络请求
仅发往天地图官方服务（*.tianditu.gov.cn）与本机代理地址（localhost），可自行审计。

代码结构（按功能拆分，便于维护与扩展）：
    constants.py    全局常量、默认配置、帮助文本
    utils.py        路径 / 查询串 / 端口 / 开机自启 / DPI 等工具函数
    config.py       配置读写（config.json）
    proxy.py        瓦片代理核心（连接池、密钥轮换、缓存、转发）
    http_server.py  本地 HTTP 服务与请求处理器
    tray.py         Windows 系统托盘（纯 ctypes）
    theme.py        界面主题（配色、ttk 样式、复选框指示器）
    table.py        GridTable 表格控件
    gui.py          tkinter 图形界面与程序入口
    tianditu_gui.py 本文件（启动入口）

文档：README.md、docs/使用说明.md、docs/打包说明.md、docs/技术手册.md
"""

from gui import main

if __name__ == "__main__":
    main()
