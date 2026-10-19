#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据 constants.APP_VERSION 生成 PyInstaller 使用的 Windows 版本资源文件。

打包时用 ``pyinstaller --version-file version_info.txt``，让 exe 的
「属性 → 详细信息」显示产品名、版本、版权等，观感更正规，也能略微降低
杀毒软件的启发式误报。

用法：
    python tools/make_version_info.py      # 生成到 <项目根>/version_info.txt
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from constants import APP_TITLE, APP_VERSION  # noqa: E402

COMPANY = "MaroD1M"
COPYRIGHT = "Copyright (c) 2025-2026 MaroD1M"
EXE_NAME = "Tianditu-ArcMap-Loader.exe"


def _ver_tuple(version):
    parts = []
    for p in str(version).split(".")[:4]:
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def main():
    v = _ver_tuple(APP_VERSION)
    vstr = ".".join(str(x) for x in v)
    text = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=%(v)r,
    prodvers=%(v)r,
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'080404B0',
        [StringStruct(u'CompanyName', u'%(company)s'),
         StringStruct(u'FileDescription', u'%(title)s'),
         StringStruct(u'FileVersion', u'%(vstr)s'),
         StringStruct(u'InternalName', u'Tianditu-ArcMap-Loader'),
         StringStruct(u'LegalCopyright', u'%(copy)s'),
         StringStruct(u'OriginalFilename', u'%(exe)s'),
         StringStruct(u'ProductName', u'%(title)s'),
         StringStruct(u'ProductVersion', u'%(vstr)s')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
""" % {"v": v, "vstr": vstr, "company": COMPANY, "title": APP_TITLE,
       "copy": COPYRIGHT, "exe": EXE_NAME}

    out = os.path.join(ROOT, "version_info.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(out)


if __name__ == "__main__":
    main()
