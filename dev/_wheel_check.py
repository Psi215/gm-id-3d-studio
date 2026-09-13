# -*- coding: utf-8 -*-
"""滚轮防误触自检: 悬停数值框/下拉框滚动时, 数值不应改变。"""
from __future__ import annotations

import os
import sys
import time
import traceback

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

CSV = os.path.join(ROOT, "csvdata", "selfgain_nch_2.5V.csv")
FAILS = []
_orig = sys.excepthook


def _hook(t, v, tb):
    FAILS.append("".join(traceback.format_exception(t, v, tb)))
    _orig(t, v, tb)


sys.excepthook = _hook


def pump(app, n=15, dt=0.02):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


def send_wheel(app, widget, dy=-120):
    pos = QPointF(widget.rect().center())
    glob = QPointF(widget.mapToGlobal(widget.rect().center()))
    ev = QWheelEvent(pos, glob, QPoint(0, 0), QPoint(0, dy),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    app.sendEvent(widget, ev)
    pump(app, 5)


def main() -> int:
    app = QApplication([])
    from gmstudio.ui.viewer import MainWindow
    w = MainWindow(restore=False)
    w.open_paths([CSV])
    pump(app, 40)
    assert w.wheel_filter is not None, "过滤器未安装"
    w.setFocus()          # 让数值框失去焦点(模拟悬停状态)

    print("== 滚轮防误触 ==")
    for name, sb in (("阈值", w.sp_thr), ("X 上限", w.sp_xmax),
                     ("平滑窗", w.sp_win)):
        before = sb.value()
        send_wheel(app, sb, -120)
        send_wheel(app, sb, 120)
        after = sb.value()
        print(f"  {name}(控件自身): {before} -> {after}", end="")
        assert before == after, f"{name} 被滚轮改动了!"
        print("  OK")
        # 真实场景: 鼠标停在数字文字上 -> 事件目标是内部 QLineEdit
        le = sb.lineEdit()
        if le is not None:
            sb.setFocus()          # 即使已获得焦点也不应改值
            before = sb.value()
            send_wheel(app, le, -120)
            print(f"  {name}(内部行编辑/有焦点): {before} -> {sb.value()}",
                  end="")
            assert before == sb.value(), f"{name} 内部行编辑被滚轮改动!"
            print("  OK")
    combo = w.cmb_disp
    before = combo.currentIndex()
    send_wheel(app, combo, -120)
    print(f"  下拉框: index {before} -> {combo.currentIndex()}", end="")
    assert before == combo.currentIndex(), "下拉框被滚轮改动了!"
    print("  OK")

    # 关闭保护后应恢复滚轮调值
    w.act_wheel.setChecked(False)
    sb = w.sp_win
    before = sb.value()
    send_wheel(app, sb, -120)
    changed = sb.value() != before
    print(f"  关闭保护后: {before} -> {sb.value()} (可调={changed})")
    w.act_wheel.setChecked(True)

    if FAILS:
        print("FAILED:", FAILS[:2])
        return 1
    print("WHEEL GUARD PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
