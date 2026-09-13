# -*- coding: utf-8 -*-
"""应用入口: 建 QApplication -> 主题 -> 主窗口。"""
from __future__ import annotations

import os
import sys


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)

    from PySide6.QtWidgets import QApplication

    from .ui.theme import apply
    from .ui.viewer import MainWindow
    from .ui.widgets import install_no_wheel_filter

    app = QApplication(argv)
    app.setApplicationName("gm/ID 设计数据工作室")
    apply(app, dark=False)
    install_no_wheel_filter(app)      # 悬停滚轮不改数值(防误触)
    files = [a for a in argv[1:] if not a.startswith("-")]
    win = MainWindow(initial_files=files or None)
    win.show()
    return app.exec()
