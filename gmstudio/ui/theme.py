# -*- coding: utf-8 -*-
"""UI 主题: 现代浅色 / 深色 QSS。"""
from __future__ import annotations

ACCENT = "#2f6fed"
ACCENT_DARK = "#3d7bf0"

_LIGHT = f"""
* {{ font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; font-size: 12px; }}
QMainWindow, QDialog {{ background: #f4f6fa; }}
QWidget#central {{ background: #f4f6fa; }}
QTabWidget::pane {{ border: 1px solid #d8dee9; border-radius: 8px; background: #ffffff; top: -1px; }}
QTabBar::tab {{ background: #e6ebf4; color: #4a5568; padding: 7px 18px; margin-right: 2px;
                border-top-left-radius: 7px; border-top-right-radius: 7px; }}
QTabBar::tab:selected {{ background: #ffffff; color: {ACCENT}; font-weight: 600;
                          border-bottom: 2px solid {ACCENT}; }}
QGroupBox {{ background: #ffffff; border: 1px solid #dde3ee; border-radius: 9px;
             margin-top: 10px; padding-top: 12px; font-weight: 600; color: #33405c; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
QPushButton {{ background: #eef2f9; border: 1px solid #cfd8e8; border-radius: 7px;
               padding: 5px 12px; color: #2b3a55; }}
QPushButton:hover {{ background: #e2eafc; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: #d4e0fa; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #2459c8; }}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{ background: #ffffff; border: 1px solid #ccd6e6;
    border-radius: 6px; padding: 3px 6px; color: #22304e; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border: 1.5px solid {ACCENT}; }}
QCheckBox {{ spacing: 6px; color: #33405c; }}
QListWidget, QTreeWidget, QTableWidget {{ background: #ffffff; border: 1px solid #d8dee9;
    border-radius: 7px; alternate-background-color: #f6f8fc; }}
QTreeWidget::item, QListWidget::item {{ padding: 2px 2px; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: #dbe7ff; color: #14305f; }}
QHeaderView::section {{ background: #edf1f8; color: #33405c; padding: 4px 6px;
    border: none; border-right: 1px solid #d8dee9; font-weight: 600; }}
QTableWidget {{ gridline-color: #e4e9f2; }}
QDockWidget {{ font-weight: 600; color: #33405c; }}
QDockWidget::title {{ background: #eaf0fa; padding: 6px 10px; border-radius: 4px; }}
QStatusBar {{ background: #eaf0fa; color: #44506b; }}
QMenuBar {{ background: #f4f6fa; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: #dbe7ff; }}
QScrollArea {{ border: none; background: transparent; }}
QSplitter::handle {{ background: #dde3ee; width: 3px; }}
QToolTip {{ background: #ffffff; border: 1px solid #b9c6dd; color: #22304e; padding: 3px 6px; }}
"""

_DARK = f"""
* {{ font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; font-size: 12px; }}
QMainWindow, QDialog {{ background: #171c26; }}
QWidget#central {{ background: #171c26; }}
QTabWidget::pane {{ border: 1px solid #2b3444; border-radius: 8px; background: #1e2532; top: -1px; }}
QTabBar::tab {{ background: #232b3a; color: #9fb0c8; padding: 7px 18px; margin-right: 2px;
                border-top-left-radius: 7px; border-top-right-radius: 7px; }}
QTabBar::tab:selected {{ background: #1e2532; color: {ACCENT_DARK}; font-weight: 600;
                          border-bottom: 2px solid {ACCENT_DARK}; }}
QGroupBox {{ background: #1e2532; border: 1px solid #2e3949; border-radius: 9px;
             margin-top: 10px; padding-top: 12px; font-weight: 600; color: #c3d1e6; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
QPushButton {{ background: #263042; border: 1px solid #39455a; border-radius: 7px;
               padding: 5px 12px; color: #c7d4e8; }}
QPushButton:hover {{ background: #2f3d55; border-color: {ACCENT_DARK}; }}
QPushButton:pressed {{ background: #35465f; }}
QPushButton#primary {{ background: {ACCENT_DARK}; color: white; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #2459c8; }}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{ background: #151a23; border: 1px solid #37435a;
    border-radius: 6px; padding: 3px 6px; color: #dce6f5; selection-background-color: {ACCENT_DARK}; }}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border: 1.5px solid {ACCENT_DARK}; }}
QCheckBox {{ spacing: 6px; color: #c3d1e6; }}
QListWidget, QTreeWidget, QTableWidget {{ background: #151a23; border: 1px solid #2b3444;
    border-radius: 7px; alternate-background-color: #1a212c; color: #d3dfef; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: #27406b; color: #e8f0ff; }}
QHeaderView::section {{ background: #232b3a; color: #c3d1e6; padding: 4px 6px;
    border: none; border-right: 1px solid #2b3444; font-weight: 600; }}
QTableWidget {{ gridline-color: #242d3c; }}
QDockWidget {{ font-weight: 600; color: #c3d1e6; }}
QDockWidget::title {{ background: #232b3a; padding: 6px 10px; border-radius: 4px; }}
QStatusBar {{ background: #1d2430; color: #9fb0c8; }}
QMenuBar {{ background: #171c26; color: #c3d1e6; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: #27406b; }}
QScrollArea {{ border: none; background: transparent; }}
QSplitter::handle {{ background: #2b3444; width: 3px; }}
QToolTip {{ background: #1e2532; border: 1px solid #3a4a63; color: #dce6f5; padding: 3px 6px; }}
"""


def apply(app, dark: bool = False):
    app.setStyleSheet(_DARK if dark else _LIGHT)
