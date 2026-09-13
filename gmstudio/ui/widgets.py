# -*- coding: utf-8 -*-
"""绘图控件: matplotlib 画布 + 工具栏 + 持久色标。"""
from __future__ import annotations

import numpy as np
from matplotlib import colormaps, rcParams
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavToolbar
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QVBoxLayout, QWidget

rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
    "Arial Unicode MS", "DejaVu Sans",
]
rcParams["axes.unicode_minus"] = False
try:
    rcParams["axes3d.mouserotationstyle"] = "trackball"
except Exception:
    pass

CMAPS = ["viridis", "plasma", "cividis", "magma", "coolwarm", "turbo"]


def getcmap(name):
    return colormaps[name]


class MplPanel(QWidget):
    """单图(matplotlib + 工具栏 + 持久色标)控件。"""

    def __init__(self, parent=None, nrows=1, projection=None,
                 constrained=True):
        super().__init__(parent)
        # 3D 面板用固定布局: constrained layout 每次重绘都会跑一遍布局求解,
        # 旋转时会明显掉帧(抖动), 这里改为固定边距。
        self.fig = Figure(figsize=(7.5, 5.2),
                          layout="constrained" if constrained else None)
        if not constrained:
            self.fig.subplots_adjust(left=0.07, right=0.86, top=0.93,
                                     bottom=0.09)
        if projection == "3d":
            self.axes = self.fig.add_subplot(111, projection="3d")
            self.axes2 = None
        elif nrows == 2:
            gs = self.fig.add_gridspec(2, 1, height_ratios=[3, 2])
            self.axes = self.fig.add_subplot(gs[0])
            self.axes2 = self.fig.add_subplot(gs[1])
        else:
            self.axes = self.fig.add_subplot(111)
            self.axes2 = None
        self.canvas = FigureCanvas(self.fig)
        self.cbar_ax = None
        self._cbar_obj = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(NavToolbar(self.canvas, self))
        lay.addWidget(self.canvas)

    def clear_all(self):
        keep = {id(self.axes)}
        if self.axes2 is not None:
            keep.add(id(self.axes2))
        if self.cbar_ax is not None:
            keep.add(id(self.cbar_ax))
        for a in list(self.fig.axes):
            if id(a) not in keep:
                self.fig.delaxes(a)
        for ax in (self.axes, self.axes2):
            if ax is not None:
                ax.clear()

    def set_colorbar(self, mappable, label=None, **kw):
        if self.cbar_ax is None:
            cb = self.fig.colorbar(mappable, ax=self.axes, **kw)
            self.cbar_ax = cb.ax
            self._cbar_obj = cb
        else:
            try:
                self._cbar_obj = self.fig.colorbar(mappable, cax=self.cbar_ax)
            except Exception:
                self.fig.delaxes(self.cbar_ax)
                cb = self.fig.colorbar(mappable, ax=self.axes, **kw)
                self.cbar_ax = cb.ax
                self._cbar_obj = cb
        if label is not None and self._cbar_obj is not None:
            self._cbar_obj.set_label(label)
        return self.cbar_ax

    def clear_colorbar(self):
        if self.cbar_ax is not None:
            try:
                self.fig.delaxes(self.cbar_ax)
            except Exception:
                pass
        self.cbar_ax = None
        self._cbar_obj = None

    def auto_view(self):
        for ax in (self.axes, self.axes2):
            if ax is None:
                continue
            try:
                if str(getattr(ax, "name", "")).startswith("3d"):
                    ax.autoscale(enable=True)
                    ax.margins(0.05)
                else:
                    ax.relim()
                    ax.autoscale_view()
                    ax.margins(0.03, 0.05)
            except Exception:
                pass


def mkspin(lo, hi, val, dec=4, step=0.1):
    from PySide6.QtWidgets import QDoubleSpinBox
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    s.setSingleStep(step)
    s.setKeyboardTracking(False)
    return s


class NoWheelFilter(QObject):
    """防止“鼠标悬停在数值框/下拉框上滚动滚轮”误改数值。

    关键点: Qt 的数值框内部是 QLineEdit 子控件, 鼠标停在数字上时事件
    目标是那个子控件而不是数值框本身, 因此必须沿父链向上判定;
    同时不再区分是否获得焦点(点进去再滚也不改值, 用键盘/箭头调即可)。

    命中的滚轮事件会被拦下, 并把滚动量转交给外层滚动区(面板仍能滚动)。
    可用 enabled 属性随时开关(视图菜单)。
    """

    VALUE_WIDGET_DEPTH = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = True

    @staticmethod
    def _is_value_widget(obj) -> bool:
        from PySide6.QtWidgets import QAbstractSpinBox, QComboBox
        w = obj
        for _ in range(NoWheelFilter.VALUE_WIDGET_DEPTH):
            if w is None:
                return False
            if isinstance(w, (QAbstractSpinBox, QComboBox)):
                return True
            w = w.parentWidget() if hasattr(w, "parentWidget") else None
        return False

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QAbstractScrollArea
        if (self.enabled and ev.type() == QEvent.Wheel
                and self._is_value_widget(obj)):
            # 把滚动交给最近的滚动区域, 但不改数值
            w = obj
            while w is not None and not isinstance(w, QAbstractScrollArea):
                w = w.parentWidget() if hasattr(w, "parentWidget") else None
            if isinstance(w, QAbstractScrollArea):
                bar = w.verticalScrollBar()
                if bar is not None and bar.isVisible():
                    try:
                        dy = ev.angleDelta().y()
                        bar.setValue(bar.value() - int(dy / 3))
                    except Exception:
                        pass
            return True
        return super().eventFilter(obj, ev)


_WHEEL_FILTER = None


def install_no_wheel_filter(app=None):
    """在应用上装一次防误触过滤器(幂等), 返回过滤器对象。"""
    global _WHEEL_FILTER
    if _WHEEL_FILTER is not None:
        return _WHEEL_FILTER
    from PySide6.QtWidgets import QApplication
    app = app or QApplication.instance()
    if app is None:
        return None
    _WHEEL_FILTER = NoWheelFilter(app)
    app.installEventFilter(_WHEEL_FILTER)
    return _WHEEL_FILTER
