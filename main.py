# -*- coding: utf-8 -*-
"""入口: python main.py [文件/文件夹 ...]

gm/ID 设计数据工作室:
一次导入 DC 全参数导出文件(total.csv 等, 114 参数 × 15 L), 全部数据
驻留内存; 右侧参数树(或独立“参数选择窗口”)实时勾选要查看的参数。
不带参数则启动空窗口, 用菜单或右侧按钮打开数据。
"""
from __future__ import annotations

import os
import sys


def _run() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    from gmstudio.app import main as app_main
    return app_main()


if __name__ == "__main__":
    raise SystemExit(_run())
