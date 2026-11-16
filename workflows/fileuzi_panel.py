#!/usr/bin/env python3
"""
FileUzi email panel: a floating window for filing .eml emails.

Started by fileuzi_rename.py when .eml files are selected (and PyQt6 is
installed). Emails are read, checked and described in the background, one
ahead of the one on screen, so each one is ready when you get to it. You
tick or untick, edit the title block if needed, and press File email. The
filing happens in the background while you look at the next email.

Install once:   sudo dnf install python3-pyqt6
"""
import ctypes.util
import html
import itertools
import json
from datetime import date
import os
import re
import sys
from pathlib import Path

# GNOME on Wayland ignores 'stay on top' for native Wayland windows; through
# XWayland it works. Only switch if Qt's X11 plugin can actually load.
if (os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY")
        and "QT_QPA_PLATFORM" not in os.environ and ctypes.util.find_library("xcb-cursor")):
    os.environ["QT_QPA_PLATFORM"] = "xcb"

from PyQt6.QtCore import QDate, QObject, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QShortcut
from PyQt6.QtWidgets import QScrollArea
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDateEdit, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QProgressBar, QPushButton, QSizePolicy, QTextBrowser, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget, QHeaderView, QAbstractItemView)

# ---------- look ----------
FILM, SHEET, GRAPHITE, LEAD, RULE = "#E8EDEF", "#FAFBFB", "#21282D", "#68747C", "#B9C3C9"
DYELINE, DYELINE_PALE, REDLINE = "#1F4E79", "#DCE7F1", "#B8321F"
UI_FONT = '"Adwaita Sans", "Inter", "Cantarell", sans-serif'
LETTER_FONT = '"Source Serif 4", "Lora", "Liberation Serif", "DejaVu Serif", serif'

STYLE = f"""
QWidget#Panel {{ background: {FILM}; }}
QWidget {{ font-family: {UI_FONT}; font-size: 10pt; color: {GRAPHITE}; }}
QLabel#Subject {{ font-size: 13.5pt; font-weight: 600; }}
QLabel#Meta, QLabel#Status, QLabel#FolderName, QLabel#Hint {{ color: {LEAD}; }}
QLabel#Meta {{ font-size: 9.5pt; }}
QLabel#Status {{ font-size: 9pt; }}
QLabel#Section {{ font-size: 10.5pt; font-weight: 600; padding-top: 6px; }}
QLabel#Hint {{ font-size: 9pt; }}
QLabel#Summary {{ background: {SHEET}; padding: 12px 14px; font-size: 9.5pt; }}
QLabel#FolderName {{ font-size: 9pt; padding: 4px 2px 0 2px; }}
QLabel#Banner {{ background: #F6E3DF; color: {REDLINE}; border-left: 3px solid {REDLINE};
                 padding: 8px 10px; }}
QProgressBar {{ background: {RULE}; border: none; max-height: 4px; }}
QProgressBar::chunk {{ background: {DYELINE}; }}
QTextBrowser#Letter {{ background: {SHEET}; border: none; border-left: 3px solid {DYELINE};
                       padding: 8px 12px; font-family: {LETTER_FONT}; font-size: 10.5pt; }}

/* the title block: square, ruled, one cell per part of the folder name */
QFrame#TitleBlock {{ background: {SHEET}; border: 1.5px solid {GRAPHITE}; }}
QFrame#Cell {{ border: none; border-right: 1px solid {GRAPHITE}; }}
QFrame#CellLast {{ border: none; }}
QFrame#CellWide {{ border: none; border-top: 1px solid {GRAPHITE}; }}
QLabel#CellLabel {{ color: {LEAD}; font-size: 8pt; }}
QPlainTextEdit#Desc {{ background: transparent; border: none; padding: 0; font-size: 11pt; font-weight: 600; }}
QPlainTextEdit#Desc:focus {{ background: {DYELINE_PALE}; }}
QPlainTextEdit#Desc[small="true"] {{ font-size: 9pt; }}
QToolButton#DescMore {{ background: transparent; border: none; color: {LEAD}; padding: 0 2px; }}
QLabel#Toast {{ background: rgba(28,27,51,0.88); color: white; border-radius: 10px; padding: 4px 12px;
                font-size: 8pt; font-weight: 600; }}
QFrame#Share {{ background: rgba(255,255,255,0.97); border: 1px solid #D9D4FF; border-radius: 12px; }}
QLabel#ShareTitle {{ font-weight: 700; font-size: 8.5pt; color: #1C1B33; background: transparent; border: none; }}
QToolButton#ShareClose {{ background: transparent; border: none; color: #6E7090; padding: 0 2px; }}
QPushButton#ShareOpen {{ background: #6A5AE0; color: white; border: none; border-radius: 9px;
                         padding: 2px 10px; font-size: 8pt; font-weight: 600; min-height: 18px; }}
QPushButton#ShareOpen:hover {{ background: #5848D0; }}
QLabel#ShareZone {{ border: 1.5px dashed #A99EF2; border-radius: 8px; color: #6E7090; font-size: 8pt;
                    background: #F6F4FF; padding: 6px; }}
QLabel#ShareZone[drop="true"] {{ background: #E9E5FF; border-color: #6A5AE0; color: #1C1B33; }}
QPushButton#SharePill {{ background: #6A5AE0; color: white; border: none; border-radius: 9px;
                         padding: 1px 9px; font-size: 7.5pt; font-weight: 600; min-height: 16px; }}
QToolButton#DescMore::menu-indicator {{ image: none; }}
QLineEdit, QComboBox, QDateEdit {{ background: transparent; border: none; padding: 1px 0;
                                   font-size: 11pt; font-weight: 500; }}
QLineEdit#Job {{ color: {DYELINE}; font-weight: 700; font-size: 13pt; }}
QComboBox#Desc {{ font-weight: 600; letter-spacing: 0.3px; }}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus {{ background: {DYELINE_PALE}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 14px; }}
QPushButton#Dir {{ background: transparent; border: none; font-size: 13pt; font-weight: 700;
                   color: {DYELINE}; text-align: left; padding: 0; }}
QPushButton#Dir:focus {{ background: {DYELINE_PALE}; }}

QListWidget, QTreeWidget {{ background: {SHEET}; border: none; outline: none; padding: 2px 0; }}
QListWidget::item, QTreeWidget::item {{ padding: 3px 4px; border: none; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {DYELINE_PALE}; color: {GRAPHITE}; }}
QHeaderView::section {{ background: {SHEET}; color: {LEAD}; border: none; font-size: 8.5pt;
                        padding: 2px 4px; }}
QCheckBox {{ color: {LEAD}; font-size: 9pt; }}
QComboBox#Picker {{ color: {LEAD}; font-size: 9pt; font-weight: 400; border: 1px dashed {RULE};
                    border-radius: 3px; padding: 0 4px; }}
QComboBox#Picker:focus, QComboBox#Picker:hover {{ border-color: {DYELINE}; color: {DYELINE}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {RULE}; border-radius: 3px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {LEAD}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0; }}

QPushButton {{ border-radius: 4px; padding: 7px 16px; font-weight: 600; }}
QPushButton#Primary {{ background: {DYELINE}; color: white; border: 1px solid {DYELINE}; }}
QPushButton#Primary:hover {{ background: #183E61; }}
QPushButton#Primary:disabled {{ background: {RULE}; border-color: {RULE}; color: {SHEET}; }}
QPushButton#Quiet {{ background: transparent; color: {GRAPHITE}; border: 1px solid {RULE}; }}
QPushButton#Quiet:hover {{ border-color: {LEAD}; }}
QPushButton:focus {{ outline: none; border: 2px solid {GRAPHITE}; }}
QPushButton#Link {{ background: transparent; border: none; color: {DYELINE}; padding: 4px 2px;
                    font-weight: 600; text-decoration: underline; }}
QLabel#Key {{ font-family: {LETTER_FONT}; font-style: italic; color: {GRAPHITE};
              border-left: 2px solid {DYELINE}; padding: 1px 0 1px 7px; }}
QLabel#Plan {{ color: {LEAD}; }}
QFrame#Group, QFrame#Base {{ background: {SHEET}; border: 1px solid {RULE}; }}
QFrame#Base {{ border-color: {GRAPHITE}; }}
QLabel#CardTitle {{ color: {LEAD}; font-size: 8.5pt; font-weight: 600; }}
QLabel#GroupFile {{ color: {GRAPHITE}; }}
QLabel#GroupFile[left="true"] {{ color: {RULE}; text-decoration: line-through; }}
QLabel#GroupFolder {{ color: {DYELINE}; font-weight: 600; }}
QLabel#Empty {{ color: {LEAD}; font-style: italic; }}
QCheckBox#Take {{ color: {GRAPHITE}; font-size: 9.5pt; }}
QCheckBox#Take[omitted="true"] {{ color: {REDLINE}; text-decoration: line-through; }}
QPushButton#X {{ background: transparent; border: none; color: {LEAD}; padding: 0; font-size: 10pt;
                 min-width: 16px; max-width: 16px; max-height: 18px; }}
QPushButton#X:hover {{ color: {REDLINE}; }}
QPushButton#Accept {{ background: transparent; border: 1px solid {RULE}; color: {DYELINE}; padding: 0;
                      min-width: 16px; max-width: 16px; min-height: 16px; max-height: 16px; border-radius: 3px; }}
QFrame#Accepted {{ background: transparent; border: 1px dashed {RULE}; }}
QLabel#AcceptedLine {{ color: {LEAD}; }}
QLabel#SupNote {{ color: {DYELINE}; font-weight: 600; }}
QLabel#GroupHead {{ color: {DYELINE}; font-weight: 700; }}
QLabel#FolderTitle {{ color: {DYELINE}; font-weight: 700; padding-bottom: 3px; }}
QPlainTextEdit#FolderTitleEdit {{ color: {DYELINE}; font-weight: 700; background: transparent; border: none; padding: 0; }}
QPlainTextEdit#FolderTitleEdit:focus {{ background: {DYELINE_PALE}; }}
QLabel#Warn {{ color: {REDLINE}; }}
QFrame#Group[drop="true"], QFrame#Base[drop="true"] {{ border: 2px solid {DYELINE}; }}
QScrollArea#Cards {{ background: transparent; border: none; }}
QWidget#CardsInner {{ background: transparent; }}
QPushButton#Arrow {{ background: transparent; color: {DYELINE}; border: 1px solid {RULE};
                     font-size: 14pt; font-weight: 600; padding: 0 0 3px 0; min-width: 26px; max-width: 26px; }}
QPushButton#Arrow:hover {{ border-color: {DYELINE}; background: {DYELINE_PALE}; }}

/* the small card: same parts, tighter */
QWidget#Panel[compact="true"] QWidget {{ font-size: 8.5pt; }}
QWidget#Panel[compact="true"] QLabel#Subject {{ font-size: 9.5pt; }}
QWidget#Panel[compact="true"] QLabel#Status, QWidget#Panel[compact="true"] QLabel#Plan {{ font-size: 8pt; }}
QWidget#Panel[compact="true"] QLabel#Key {{ font-size: 8.5pt; }}
QWidget#Panel[compact="true"] QLabel#CellLabel {{ font-size: 7pt; }}
QWidget#Panel[compact="true"] QLineEdit, QWidget#Panel[compact="true"] QComboBox,
QWidget#Panel[compact="true"] QDateEdit {{ font-size: 9pt; }}
QWidget#Panel[compact="true"] QLineEdit#Job, QWidget#Panel[compact="true"] QPushButton#Dir {{ font-size: 10.5pt; }}
QWidget#Panel[compact="true"] QPushButton {{ padding: 4px 10px; }}
QWidget#Panel[compact="true"] QPushButton#Link {{ padding: 4px 0; }}
QWidget#Panel[compact="true"] QPushButton#Dir {{ padding: 0; }}
QWidget#Panel[compact="true"] QPushButton#Arrow {{ padding: 0 0 3px 0; font-size: 13pt; }}
QWidget#Panel[compact="true"] QLabel#Section {{ font-size: 9pt; padding-top: 2px; }}
QWidget#Panel[compact="true"] QListWidget::item, QWidget#Panel[compact="true"] QTreeWidget::item {{ padding: 1px 2px; }}
QWidget#Panel[compact="true"] QComboBox#Picker {{ font-size: 8pt; min-height: 17px; }}
QWidget#Panel[compact="true"] QCheckBox#Take {{ font-size: 8.5pt; }}
QWidget#Panel[compact="true"] QPushButton#X {{ padding: 0; min-height: 14px; max-height: 16px; font-size: 9pt; }}
QWidget#Panel[compact="true"] QPushButton#Accept {{ padding: 0; }}
QWidget#Panel[compact="true"] QLabel#CardTitle {{ font-size: 7.5pt; }}
QWidget#Panel[compact="true"] QComboBox, QWidget#Panel[compact="true"] QLineEdit,
QWidget#Panel[compact="true"] QDateEdit {{ min-height: 19px; padding: 0; }}
QWidget#Panel[compact="true"] QComboBox#Desc, QWidget#Panel[compact="true"] QPlainTextEdit#Desc,
QWidget#Panel[compact="true"] QPlainTextEdit#FolderTitleEdit {{ font-size: 8.5pt; letter-spacing: 0; }}
QWidget#Panel[compact="true"] QPlainTextEdit#Desc[small="true"] {{ font-size: 7pt; }}
QWidget#Panel[compact="true"] QTextBrowser#Letter {{ font-size: 8.5pt; padding: 3px 6px;
                                                    border-left: 2px solid {DYELINE}; }}
QWidget#Panel[compact="true"] QLabel#CellLabel {{ font-size: 7.5pt; }}
QWidget#Panel[compact="true"] QLabel#Key {{ border-left: 2px solid {DYELINE}; padding-left: 7px; }}
QPushButton#Primary:focus {{ border: 2px solid {GRAPHITE}; }}
"""

# ---------- Aero theme: glass on a painted sky ----------
THEME = "glass"           # "glass" (white cards on soft colour), "aero" (glossy) or "drafting" (title block)

AERO_INK, AERO_SOFT, AERO_BLUE, AERO_RED = "#0E2F4C", "#2F5F86", "#0B6FB8", "#C0392B"
GLASS = ("qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(255,255,255,238), "
         "stop:0.5 rgba(246,251,255,222), stop:1 rgba(226,241,252,212))")
GLASS_EDGE = "rgba(64,128,180,150)"


def gloss(top, mid_hi, mid_lo, bottom):
    """The Aero gel: bright top half, a hard step at the middle, glow at the bottom."""
    return (f"qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {top}, stop:0.48 {mid_hi}, "
            f"stop:0.52 {mid_lo}, stop:1 {bottom})")


def aero_icons():
    """Tick-box images (Qt style sheets need files for these)."""
    folder = Path.home() / ".cache" / "fileuzi-panel"
    folder.mkdir(parents=True, exist_ok=True)
    tick = folder / "tick.svg"
    part = folder / "part.svg"
    tick.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14"><path d="M3 7.2 6 10 11 3.8" '
                    'fill="none" stroke="#0B5FA0" stroke-width="2.2" stroke-linecap="round" '
                    'stroke-linejoin="round"/></svg>')
    part.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14"><rect x="3.5" y="6" '
                    'width="7" height="2.4" rx="1" fill="#0B5FA0"/></svg>')
    return tick.as_posix(), part.as_posix()


def aero_style():
    tick, part = aero_icons()
    return f"""
QWidget#Panel {{ background: transparent; }}
QWidget {{ color: {AERO_INK}; }}
QLabel#Subject {{ color: #0A3558; }}
QLabel#Meta, QLabel#Status, QLabel#Hint, QLabel#FolderName, QLabel#Plan, QLabel#CardTitle,
QLabel#CellLabel, QLabel#Empty {{ color: {AERO_SOFT}; }}
QLabel#Banner {{ background: rgba(255,236,232,230); color: {AERO_RED}; border: 1px solid rgba(192,57,43,140);
                 border-radius: 7px; }}

QProgressBar {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #EAF3F9, stop:1 #C6DAE8);
                border: none; border-bottom: 1px solid #8FB2CC; max-height: 6px; }}
QProgressBar::chunk {{ background: {gloss('#C4F7B0', '#6CD957', '#34B82D', '#78E464')}; }}

/* glass panels */
QTextBrowser#Letter, QFrame#TitleBlock, QFrame#Group, QFrame#Base, QLabel#Summary {{
    background: {GLASS}; border: 1px solid {GLASS_EDGE}; border-radius: 8px; }}
QTextBrowser#Letter {{ font-family: {UI_FONT}; padding: 6px 10px; }}
QFrame#Base {{ border: 1px solid rgba(11,111,184,200); }}
QFrame#Cell {{ border: none; border-right: 1px solid rgba(64,128,180,80); }}
QFrame#CellWide {{ border: none; border-top: 1px solid rgba(64,128,180,80); }}
QFrame#CellLast {{ border: none; }}
QLineEdit#Job, QPushButton#Dir {{ color: {AERO_BLUE}; }}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus {{ background: rgba(140,210,255,90); border-radius: 3px; }}
QLabel#GroupFolder, QPushButton#Link {{ color: {AERO_BLUE}; }}
QPushButton#Link {{ text-decoration: none; }}
QPushButton#Link:hover {{ text-decoration: underline; }}
QCheckBox#Take {{ color: {AERO_INK}; }}
QCheckBox#Take[omitted="true"] {{ color: {AERO_RED}; }}
QLabel#GroupFile[left="true"] {{ color: #9DB6C9; }}

/* gel buttons */
QPushButton {{ border-radius: 9px; }}
QPushButton#Primary {{ color: white; border: 1px solid #1E7A19;
                       background: {gloss('#A6F290', '#52C941', '#2BA525', '#5ED34C')}; }}
QPushButton#Primary:hover {{ background: {gloss('#C2FAAE', '#66D955', '#35B82E', '#73E35F')}; }}
QPushButton#Primary:pressed {{ background: {gloss('#5ED34C', '#2BA525', '#22901D', '#52C941')}; }}
QPushButton#Primary:disabled {{ color: #EEF4F8; border-color: #9DB3C4;
                                background: {gloss('#E3ECF2', '#C9D7E2', '#B9CAD7', '#CCDAE5')}; }}
QPushButton#Quiet {{ color: {AERO_INK}; border: 1px solid #8EA9BF;
                     background: {gloss('#FFFFFF', '#EEF3F7', '#DBE5EE', '#EEF5FA')}; }}
QPushButton#Quiet:hover {{ border-color: #3E8CC8; background: {gloss('#FFFFFF', '#E7F4FD', '#CDE6F8', '#E6F5FE')}; }}
QPushButton#Arrow {{ color: white; border: 1px solid #1D5F99; border-radius: 13px;
                     background: {gloss('#B4E2FF', '#4FA9EA', '#1F86D4', '#5DBBF6')}; }}
QPushButton#Arrow:hover {{ background: {gloss('#CDEBFF', '#66B7F0', '#2B94DF', '#76C8FA')}; }}
QPushButton#X {{ color: #6C8EA8; border: none; background: transparent; }}
QPushButton#X:hover {{ color: {AERO_RED}; }}
QPushButton:focus {{ border: 1px solid #2F8CE0; }}
QPushButton#Primary:focus {{ border: 1px solid #10560C; }}
QComboBox#Picker {{ color: {AERO_SOFT}; border: 1px solid rgba(64,128,180,140); border-radius: 9px;
                    padding: 0 8px; background: {gloss('#FFFFFF', '#F3F8FC', '#E5EFF7', '#F1F7FC')}; }}
QComboBox#Picker:hover {{ color: {AERO_BLUE}; border-color: #3E8CC8; }}

/* glossy tick boxes */
QCheckBox::indicator, QTreeWidget::indicator, QListWidget::indicator {{
    width: 13px; height: 13px; border: 1px solid #6F9BBE; border-radius: 3px;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #FFFFFF, stop:1 #D6E8F6); }}
QCheckBox::indicator:hover {{ border-color: #2F8CE0; }}
QCheckBox::indicator:checked {{ image: url({tick}); }}
QCheckBox::indicator:indeterminate {{ image: url({part}); }}

QScrollBar::handle:vertical {{ border-radius: 3px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #9ED3F6, stop:0.5 #5AAFE8, stop:1 #8CCBF3); }}

/* the small card: same glass, slimmer */
QWidget#Panel[compact="true"] QTextBrowser#Letter {{ border: 1px solid {GLASS_EDGE}; border-radius: 6px;
                                                    padding: 3px 6px; }}
QWidget#Panel[compact="true"] QPushButton#Arrow {{ border-radius: 12px; }}
QWidget#Panel[compact="true"] QPushButton#X {{ border: none; }}
QWidget#Panel[compact="true"] QComboBox#Picker {{ padding: 0 8px; }}
"""


def paint_sky(widget):
    """The backdrop: soft sky, a glow, glass bubbles and a green aurora swoosh."""
    from PyQt6.QtCore import QPointF, QRectF
    from PyQt6.QtGui import QBrush, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
    w, h = widget.width(), widget.height()
    p = QPainter(widget)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    sky = QLinearGradient(0, 0, 0, h)
    sky.setColorAt(0, QColor("#F4FBFF"))
    sky.setColorAt(0.45, QColor("#CFEAFB"))
    sky.setColorAt(1, QColor("#8FCBF0"))
    p.fillRect(widget.rect(), sky)
    glow = QRadialGradient(QPointF(w * 0.15, h * 0.05), max(w, h) * 0.7)
    glow.setColorAt(0, QColor(255, 255, 255, 190))
    glow.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillRect(widget.rect(), QBrush(glow))
    # aurora: two soft green-to-aqua ribbons along the bottom
    for lift, alpha in ((0.80, 70), (0.86, 110)):
        path = QPainterPath(QPointF(0, h * lift))
        path.cubicTo(QPointF(w * 0.35, h * (lift - 0.10)), QPointF(w * 0.65, h * (lift + 0.08)),
                     QPointF(w, h * (lift - 0.06)))
        path.lineTo(w, h)
        path.lineTo(0, h)
        path.closeSubpath()
        band = QLinearGradient(0, h * (lift - 0.1), 0, h)
        band.setColorAt(0, QColor(160, 235, 120, alpha))
        band.setColorAt(0.5, QColor(70, 200, 160, alpha))
        band.setColorAt(1, QColor(40, 150, 210, alpha // 2))
        p.fillPath(path, QBrush(band))
    # glass bubbles, top right
    for cx, cy, r in ((0.86, 0.10, 0.10), (0.72, 0.05, 0.045), (0.95, 0.24, 0.035)):
        c, rad = QPointF(w * cx, h * cy), min(w, h) * r * 2.2
        bubble = QRadialGradient(QPointF(c.x() - rad * 0.35, c.y() - rad * 0.4), rad * 1.3)
        bubble.setColorAt(0, QColor(255, 255, 255, 170))
        bubble.setColorAt(0.6, QColor(200, 235, 255, 40))
        bubble.setColorAt(1, QColor(120, 190, 240, 70))
        p.setBrush(QBrush(bubble))
        p.setPen(QPen(QColor(255, 255, 255, 150), 1))
        p.drawEllipse(c, rad, rad)
    p.end()


# ---------- Glass theme: white cards on soft colour light ----------
G_INK, G_SOFT, G_VIOLET, G_PINK, G_BG = "#1C1B33", "#6E7090", "#6A5AE0", "#F0688A", "#EEF0FA"
G_TONES = [("#5B86F2", "#82A6FA"), ("#6F5FEA", "#9A8BF6"), ("#F27D9C", "#F7A9B6")]   # group tiles


def glass_icons():
    folder = Path.home() / ".cache" / "fileuzi-panel"
    folder.mkdir(parents=True, exist_ok=True)
    tick, part = folder / "tick-white.svg", folder / "part-white.svg"
    tick.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14"><path d="M3.2 7.3 6 10 10.8 4" '
                    'fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    part.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14"><rect x="3.5" y="6" width="7" '
                    'height="2.4" rx="1.2" fill="#fff"/></svg>')
    return tick.as_posix(), part.as_posix()


def glass_style():
    tick, part = glass_icons()
    heavy = '"Inter Display", "Adwaita Sans", "Inter", "Cantarell", sans-serif'
    tiles = "".join(
        f'QFrame#Group[tone="{i}"] {{ border: none; border-radius: 14px; background: qlineargradient('
        f'x1:0,y1:0,x2:1,y2:1, stop:0 {a}, stop:1 {b}); }}\n' for i, (a, b) in enumerate(G_TONES))
    return f"""
QWidget#Panel {{ background: transparent; }}
QWidget {{ color: {G_INK}; }}
QLabel#Subject {{ font-family: {heavy}; font-weight: 800; color: {G_INK}; letter-spacing: -0.2px; }}
QLabel#Meta, QLabel#Status, QLabel#Hint, QLabel#FolderName, QLabel#Plan, QLabel#CellLabel,
QLabel#Empty {{ color: {G_SOFT}; }}
QLabel#Banner {{ background: white; color: {G_PINK}; border: none; border-radius: 12px; }}
QProgressBar {{ background: rgba(255,255,255,150); border: none; max-height: 4px; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {G_VIOLET}, stop:1 {G_PINK}); }}

/* white cards, no borders: soft shadows do the edges */
QTextBrowser#Letter, QFrame#TitleBlock, QFrame#Base, QLabel#Summary {{
    background: rgba(255,255,255,235); border: none; border-radius: 14px; }}
QTextBrowser#Letter {{ font-family: {UI_FONT}; padding: 8px 12px; color: #3A3B57; }}
QFrame#Cell {{ border: none; border-right: 1px solid #ECEDF6; }}
QFrame#CellWide {{ border: none; border-top: 1px solid #ECEDF6; }}
QFrame#CellLast {{ border: none; }}
QLineEdit#Job, QPushButton#Dir {{ font-family: {heavy}; font-weight: 800; color: {G_VIOLET}; }}
QComboBox#Desc, QPlainTextEdit#Desc {{ font-family: {heavy}; font-weight: 800; }}
QPlainTextEdit#Desc:focus {{ background: #F1EFFF; border-radius: 4px; }}
QToolButton#DescMore {{ color: {G_SOFT}; }}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus {{ background: #F1EFFF; border-radius: 4px; }}
QLabel#CardTitle {{ color: {G_SOFT}; font-family: {heavy}; font-weight: 800; }}
QCheckBox#Take {{ color: {G_INK}; }}
QCheckBox#Take[omitted="true"] {{ color: {G_PINK}; }}
QPushButton#Link {{ color: {G_VIOLET}; text-decoration: none; font-family: {heavy}; font-weight: 800; }}
QPushButton#Link:hover {{ color: {G_PINK}; }}

/* the group tiles: blue, violet, pink in turn, white text */
{tiles}
QFrame#Group QLabel {{ color: white; }}
QFrame#Group QLabel#CardTitle {{ color: rgba(255,255,255,200); }}
QFrame#Group QLabel#GroupFolder {{ color: white; font-family: {heavy}; font-weight: 800; }}
QFrame#Group QLabel#GroupHead {{ color: white; font-family: {heavy}; font-weight: 800; font-size: 9.5pt; }}
QFrame#Group QLabel#Empty {{ color: rgba(255,255,255,210); }}
QFrame#Group QLabel#GroupFile[left="true"] {{ color: rgba(255,255,255,120); }}
QFrame#Group QPushButton#X {{ color: rgba(255,255,255,190); }}
QPushButton#Accept {{ color: {G_VIOLET}; background: white; border: none; border-radius: 9px; padding: 0;
                      min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px; font-size: 9pt; }}
QPushButton#Accept:hover {{ background: #F1EFFF; }}
QFrame#Group[drop="true"] {{ border: 2px solid white; }}
QFrame#Base[drop="true"] {{ border: 2px dashed {G_VIOLET}; }}
QPushButton#Link[drop="true"] {{ color: {G_PINK}; }}
QFrame#Accepted {{ background: rgba(255,255,255,150); border: 1px dashed #CFC9F5; border-radius: 12px; }}
QLabel#AcceptedLine {{ color: {G_SOFT}; }}
QFrame#Group QLabel#SupNote {{ color: white; font-weight: 600; }}
QFrame#Group QLabel#Warn {{ color: white; font-weight: 600; background: rgba(255,255,255,40);
                            border-radius: 6px; padding: 2px 5px; }}
QFrame#Group QCheckBox#FixTick {{ color: white; font-weight: 800; }}
QLabel#Take {{ color: {G_INK}; }}
QLabel#FolderTitle {{ color: {G_VIOLET}; font-family: {heavy}; font-weight: 800; padding: 0 0 3px 0; margin: 0; }}
QPlainTextEdit#FolderTitleEdit {{ color: {G_VIOLET}; font-family: {heavy}; font-weight: 800; background: transparent;
                                  border: none; padding: 0; }}
QPlainTextEdit#FolderTitleEdit:focus {{ background: #F1EFFF; border-radius: 4px; }}
QFrame#Group QPushButton#X:hover {{ color: white; }}
QFrame#Group QComboBox#Picker {{ color: white; background: rgba(255,255,255,55);
                                 border: 1px solid rgba(255,255,255,120); border-radius: 9px; padding: 0 8px; }}
QFrame#Group QComboBox#Picker:hover {{ background: rgba(255,255,255,90); }}
QFrame#Group QComboBox:!editable {{ color: white; }}
QFrame#Group QComboBox {{ background: rgba(255,255,255,40); border-radius: 6px; color: white; }}

/* buttons: coral pill, white pill, periwinkle circle */
QPushButton {{ border-radius: 15px; font-family: {heavy}; font-weight: 800; }}
QPushButton#Primary {{ color: white; border: none;
                       background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #F3687F, stop:1 #F7959B); }}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #F57890, stop:1 #F9A6AB); }}
QPushButton#Primary:pressed {{ background: #E95B74; }}
QPushButton#Primary:disabled {{ color: white; background: #D9DAE8; }}
QPushButton#Quiet {{ color: {G_INK}; border: none; background: white; }}
QPushButton#Quiet:hover {{ background: #F7F6FF; }}
QPushButton#Arrow {{ color: white; border: none; border-radius: 13px;
                     background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #9CAAF6, stop:1 #7F8EF0); }}
QPushButton#Arrow:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ADB9F8, stop:1 #8E9CF3); }}
QPushButton#X {{ color: #A3A5BD; border: none; background: transparent; }}
QPushButton#X:hover {{ color: {G_PINK}; }}
QPushButton:focus, QPushButton#Quiet:focus {{ border: 2px solid rgba(106,90,224,110); }}
QPushButton#Primary:focus {{ border: 2px solid rgba(255,255,255,170); }}
QPushButton#Link:focus, QPushButton#X:focus {{ border: none; }}
QComboBox#Picker {{ color: {G_SOFT}; border: 1px solid #E3E4F2; border-radius: 9px; padding: 0 8px;
                    background: white; }}

/* tick boxes: violet when ticked */
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 5px; border: 1.5px solid #CFD1E6;
                        background: white; }}
QCheckBox::indicator:hover {{ border-color: {G_VIOLET}; }}
QCheckBox::indicator:checked {{ border: none; image: url({tick});
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #8B7CF6, stop:1 {G_VIOLET}); }}
QCheckBox::indicator:indeterminate {{ border: none; image: url({part}); background: {G_VIOLET}; }}
QScrollBar::handle:vertical {{ background: rgba(106,90,224,90); border-radius: 3px; }}

/* the small card */
QWidget#Panel[compact="true"] QLabel#Subject {{ font-size: 10.5pt; }}
QWidget#Panel[compact="true"] QTextBrowser#Letter {{ border: none; border-radius: 12px; padding: 4px 8px; }}
QWidget#Panel[compact="true"] QPushButton {{ padding: 4px 10px; border-radius: 11px; }}
QWidget#Panel[compact="true"] QPushButton#Link {{ border-radius: 0; }}
QWidget#Panel[compact="true"] QPushButton#Arrow {{ border-radius: 12px; }}
QWidget#Panel[compact="true"] QPushButton#X {{ border: none; padding: 0; }}
QWidget#Panel[compact="true"] QComboBox#Picker {{ padding: 0 8px; }}
QWidget#Panel[compact="true"] QPushButton#Dir {{ padding: 0; }}
QWidget#Panel[compact="true"] QPushButton#Accept {{ padding: 0; border-radius: 9px; }}
"""


def paint_glass(widget):
    """Pale lavender, with big soft glows of violet, pink and coral."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QBrush, QLinearGradient, QPainter, QRadialGradient
    w, h = widget.width(), widget.height()
    p = QPainter(widget)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    base = QLinearGradient(0, 0, w, h)
    base.setColorAt(0, QColor("#F6F4FD"))
    base.setColorAt(1, QColor("#E9ECFA"))
    p.fillRect(widget.rect(), base)
    for cx, cy, r, colour in ((1.05, 0.30, 0.55, (124, 108, 246, 120)),
                              (0.95, 0.95, 0.70, (244, 120, 150, 110)),
                              (0.20, 1.05, 0.55, (249, 170, 130, 90)),
                              (-0.10, 0.05, 0.45, (170, 190, 255, 80))):
        g = QRadialGradient(QPointF(w * cx, h * cy), max(w, h) * r)
        g.setColorAt(0, QColor(*colour))
        g.setColorAt(1, QColor(colour[0], colour[1], colour[2], 0))
        p.fillRect(widget.rect(), QBrush(g))
    p.end()


def soft_shadow(widget, colour=(70, 60, 160, 45), blur=22, dy=5):
    """The glass theme's edges: a soft coloured shadow instead of a border."""
    if THEME != "glass":
        return
    from PyQt6.QtWidgets import QGraphicsDropShadowEffect
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(blur)
    fx.setOffset(0, dy)
    fx.setColor(QColor(*colour))
    widget.setGraphicsEffect(fx)


if THEME == "aero":
    STYLE = STYLE + aero_style()
elif THEME == "glass":
    STYLE = STYLE + glass_style()

# open drop-down lists: dark text on white in every theme (inside the blue group
# cards they were inheriting the white button text: white on white)
STYLE += """
QComboBox QAbstractItemView, QFrame#Group QComboBox#Picker QAbstractItemView {
    background: #FFFFFF; color: #1C1B33; border: 1px solid #D9D4FF; border-radius: 6px;
    selection-background-color: #6A5AE0; selection-color: #FFFFFF; outline: 0; padding: 2px; }
QComboBox QAbstractItemView::item, QFrame#Group QComboBox#Picker QAbstractItemView::item {
    color: #1C1B33; background: transparent; min-height: 20px; padding: 2px 6px; }
QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:hover,
QFrame#Group QComboBox#Picker QAbstractItemView::item:selected,
QFrame#Group QComboBox#Picker QAbstractItemView::item:hover {
    background: #6A5AE0; color: #FFFFFF; }
"""



# ---------- background worker: reading, describing and filing ----------

class Worker(QObject):
    planned = pyqtSignal(int, object)
    replanned = pyqtSignal(int, object)
    filed = pyqtSignal(int, object)
    status = pyqtSignal(str)

    def __init__(self, fz, emails, modes):
        super().__init__()
        self.fz, self.emails, self.modes = fz, emails, modes
        self.extra = {}                                    # files dropped on an email's card

    @pyqtSlot(int)
    def plan(self, i):
        mode = self.modes[i]
        if mode == "email" and not getattr(self, "warmed", False):
            self.warmed = True                                 # (first email only: the start-up card is up)
            if self.fz.USE_LLM and Path(self.fz.LLM_MODEL).expanduser().is_file():
                self.status.emit("Starting the description writer")
                self.fz.get_llm(wait=True)
        timer = self.fz.StageTimer(self.status.emit)          # each step's time -> timing.log
        try:
            if mode == "email":
                p = self.fz.plan_email(self.emails[i], timer, extra=self.extra.get(i))
                p["mode"] = "email"
            elif mode == "check":
                p = self.fz.plan_check(self.emails[i], self.status.emit)
            else:
                p = self.fz.plan_folder(self.emails[i], mode, self.status.emit)
        except Exception as e:
            p = {"eml": self.emails[i], "mode": mode, "error": f"Couldn't read {self.emails[i].name}: {e}"}
        if mode == "email":
            timer.done()
        self.status.emit("")
        self.planned.emit(i, p)

    @pyqtSlot(int, object, str)
    def replan_also(self, i, plan, job):
        plan["job"] = job
        try:
            if plan.get("mode") == "email":
                self.fz.plan_email_also(plan, self.status.emit)
            else:
                self.fz.plan_folder_also(plan, self.status.emit)
        except Exception as e:
            plan["also"] = {"warning": f"Couldn't work out where else to file: {e}", "job_root": None}
        self.status.emit("")
        self.replanned.emit(i, plan)

    @pyqtSlot(int, object, object)
    def file(self, i, plan, c):
        fz, result = self.fz, {"name": plan["eml"].name, "ok": False, "lines": []}
        timer = fz.StageTimer(self.status.emit)                 # filing steps -> timing.log too
        timer(f"Filing (writing files and the email PDF)")
        mode = plan.get("mode", "email")
        if mode == "check":
            try:
                result["lines"].append(fz.apply_check(plan, c["fix"]))
                result["ok"], result["folder"] = True, f"Current Drawings, {plan['root'].name}"
            except Exception as e:
                result["lines"].append(f"Fixing failed: {e!r}")
            self.status.emit("")
            self.filed.emit(i, result)
            return
        try:
            if mode == "email":
                folder, problems = fz.file_email(plan, c["rows"], c["pdf"], c["job"], c["direction"],
                                                 c["who"], c["desc"], c["when"], status=timer)
            else:                                          # a folder: rename it (IN / OUT) or leave it (also)
                folder, problems = fz.file_folder(plan, c), []
                if mode == "out" and (date.today() - c["when"]).days in (0, 1):
                    result["offer_email"] = (folder, c["job"], c["who"], c["desc"])
            result["lines"] += problems
            if folder and not (problems and "NOT removed" in problems[0]):
                result["ok"], result["folder"] = True, folder.name
                also = plan.get("also")
                if c["routes"] and also and also.get("job_root") and also["job"] == c["job"]:
                    # 'PDF of the email' -> the PDF (or screenshots) just written
                    attached = {a["name"] for a in plan["atts"]}
                    made = {f.name for f in folder.iterdir() if f.is_file() and f.name not in attached}
                    routes = [(rel, name, {m for f in files for m in (made if f == fz.PDF_ROW else {f})})
                              for rel, name, files in c["routes"]]
                    timer("Filing: copies to other folders")
                    with fz.Waited("copies to other folders"):
                        text = fz.run_also(also, [], folder, desc=c["desc"], routes=routes,
                                           confirm=lambda moves: True)     # approved in the panel
                    if text:
                        result["lines"].append(text)
                timer("Filing: recording it in the examples database")
                fz.record_example(plan, c, folder.name)             # for Hermes: suggested vs filed
                if plan.get("share_links") and any(a.get("dropped") for a in plan.get("atts", [])):
                    with fz.Waited("remembering the share links (history file)"):
                        fz.remember_share_links(plan, folder.name)  # don't offer those links again
        except Exception as e:
            result["lines"].append(f"Filing failed: {e!r}")
        finally:
            fz.drop_staging(plan)
            timer.done()
        self.status.emit("")
        self.filed.emit(i, result)


# ---------- the panel ----------

def cell(label, field, name="Cell"):
    box = QFrame()
    box.setObjectName(name)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(8, 4, 8, 5)
    lay.setSpacing(0)
    tag = QLabel(label)
    tag.setObjectName("CellLabel")
    tag.setMinimumWidth(0)
    lay.addWidget(tag)
    lay.addWidget(field, 1)
    return box, tag


def short_folder(rel, title=False):
    """'2505_ADMIN/2505_P_PLANNING' -> '2505_P_PLANNING' (or 'P Planning' for sentences)."""
    last = rel.rstrip("/").split("/")[-1]
    if not title:
        return last
    words = re.sub(r"^[A-Za-z]?-?\d{3,5}[_ -]+", "", last)
    words = re.sub(r"^[A-Z][_ ](?=[A-Z])", "", words)          # '2505_P_PLANNING' -> 'PLANNING'
    return words.replace("_", " ").replace("-", " ").title()


def section(text):
    lab = QLabel(text)
    lab.setProperty("working", True)
    lab.setObjectName("Section")
    return lab


def tidy_label(label):
    """'Current Drawings  (your drawings only)  (2 found)  → a, b' -> readable detail."""
    parts = [p.strip() for p in re.split(r"\s{2,}", label or "") if p.strip()]
    files = next((p for p in parts if p.startswith("→")), "")
    notes = [p.strip("()") for p in parts[1:] if not p.startswith("→")]
    words = {"your drawings only": "Your drawings only", "NEW FOLDER": "New folder, made if ticked",
             "you'll name the folder": "You name the folder"}
    notes = [words.get(n, n) for n in notes if n != "keyword" and not n.startswith("model ")]
    notes = [re.sub(r"^(\d+) older to Superseded$", r"\1 older revision moves to Superseded", n) for n in notes]
    notes = [re.sub(r"^(\d+) found$", r"\1 of yours", n) for n in notes]
    text = ", ".join(notes)
    if files:                                     # files on their own line
        text = (text + "\n" if text else "") + files.lstrip("→ ").strip()
    return parts[0] if parts else "", text


# ---------- two small widgets: the description box and the progress segments ----------

class DescBox(QWidget):
    """The description: wraps onto two lines (scrolls if longer), with the
    other suggestions on a small ▾ button. Behaves like the old drop-down for
    the rest of the code: currentText(), clear(), addItems(), editTextChanged."""
    editTextChanged = pyqtSignal(str)
    LINES = 3                                          # grows to 3 lines, then scrolls

    def __init__(self):
        super().__init__()
        from PyQt6.QtWidgets import QPlainTextEdit, QToolButton, QMenu
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.edit = QPlainTextEdit()
        self.edit.setObjectName("Desc")
        self.edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.edit.setTabChangesFocus(True)
        self.edit.document().setDocumentMargin(1)
        self.edit.installEventFilter(self)
        self.more = QToolButton()
        self.more.setObjectName("DescMore")
        self.more.setText("▾")
        self.more.setToolTip("Other suggested descriptions")
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self.more)
        self.more.setMenu(self.menu)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.more, 0, Qt.AlignmentFlag.AlignTop)
        self.items = []
        self.edit.textChanged.connect(lambda: self.editTextChanged.emit(self.currentText()))
        self.edit.textChanged.connect(lambda: QTimer.singleShot(0, self.fit))

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self.edit and event.type() == QEvent.Type.KeyPress and \
                event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return True                                    # one line of text: Enter doesn't break it
        return super().eventFilter(obj, event)

    def fit(self):
        """Always the height of two lines, so the card never changes shape. A
        description that needs three lines is set a little smaller to fit."""
        self.edit.ensurePolished()
        if not hasattr(self, "base_spacing"):
            self.base_spacing = self.edit.fontMetrics().lineSpacing()
        h = self.base_spacing * 2 + 10
        if self.edit.height() != h:
            self.edit.setFixedHeight(h)
        layout = self.edit.document().documentLayout()
        for small in (False, True):
            if bool(self.edit.property("small")) != small:
                self.edit.setProperty("small", small)
                self.edit.style().unpolish(self.edit)
                self.edit.style().polish(self.edit)
            lines = int(round(layout.documentSize().height()))
            if lines * self.edit.fontMetrics().lineSpacing() <= h - 8:
                break

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self.fit)                     # wrapping depends on the width

    def currentText(self):
        return " ".join(self.edit.toPlainText().split())

    def setText(self, text):
        self.edit.setPlainText(text)
        c = self.edit.textCursor()
        c.movePosition(c.MoveOperation.Start)
        self.edit.setTextCursor(c)
        self.fit()

    def clear(self):
        self.items = []
        self.menu.clear()
        self.edit.clear()

    def addItems(self, items):
        for t in items:
            if t and t not in self.items:
                self.items.append(t)
                self.menu.addAction(t, lambda t=t: self.setText(t))
        if not self.currentText() and self.items:
            self.setText(self.items[0])
        self.more.setEnabled(len(self.items) > 1)

    def setToolTip(self, text):
        self.edit.setToolTip(text)


class Segments(QWidget):
    """One segment per email: filed/skipped = filled, the one on screen =
    outlined, still to come = pale. One continuous bar for long batches."""

    def __init__(self, total):
        super().__init__()
        self.total, self.value, self.current = max(total, 1), 0, 0
        self.setFixedHeight(8)

    def setRange(self, low, high):
        self.total = max(high, 1)
        self.update()

    def setValue(self, v):
        self.value = v
        self.update()

    def setCurrent(self, i):
        self.current = i
        self.update()

    def paintEvent(self, e):
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QLinearGradient, QPainter, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        done_a, done_b, todo, edge = {
            "glass": ("#6A5AE0", "#F0688A", QColor(255, 255, 255, 190), QColor("#6A5AE0")),
            "aero": ("#34B82D", "#78E464", QColor(255, 255, 255, 170), QColor("#1F86D4")),
        }.get(THEME, (DYELINE, DYELINE, QColor(RULE), QColor(GRAPHITE)))
        w, h = self.width(), self.height()
        fill = QLinearGradient(0, 0, w, 0)
        fill.setColorAt(0, QColor(done_a))
        fill.setColorAt(1, QColor(done_b))
        n = self.total
        gap = 3 if n <= 24 else 0
        seg = (w - gap * (n - 1)) / n if n <= 24 else w
        r = h / 2
        if n > 24:                                         # long batch: one bar
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(todo)
            p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
            p.setBrush(fill)
            p.drawRoundedRect(QRectF(0, 0, w * self.value / n, h), r, r)
        else:
            for i in range(n):
                rect = QRectF(i * (seg + gap), 0, seg, h)
                if i < self.value:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(fill)
                elif i == self.current:
                    p.setPen(QPen(edge, 1.4))
                    p.setBrush(todo)
                    rect = rect.adjusted(0.7, 0.7, -0.7, -0.7)
                else:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(todo)
                p.drawRoundedRect(rect, r, r)
        p.end()


class Splash(QWidget):
    """Shown while FileUzi gets going, until the first card is ready: a turning
    ring, the step it's on now, and the steps already done (ticked)."""

    def __init__(self, total=0, kind="email"):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setFixedSize(Panel.CARD_SIZE[0], 168)
        self.angle, self.current, self.done = 0, "Opening FileUzi", []
        word = {"email": "email", "check": "job", "in": "folder", "out": "folder", "also": "folder"}.get(kind, "item")
        self.subtitle = f"{total} {word}{'s' if total != 1 else ''} to go through" if total else ""
        self.spin = QTimer(self)
        self.spin.timeout.connect(self.turn)
        self.spin.start(30)

    def turn(self):
        self.angle = (self.angle + 9) % 360
        self.update()

    def step(self, text):
        """A worker status line ('Checking images (logos ...)') becomes the current step."""
        text = (text or "").split(" (")[0].strip().rstrip("….")
        if not text or text == self.current:
            return
        if self.current and self.current not in self.done:
            self.done.append(self.current)
        self.current = text
        self.update()

    def paintEvent(self, e):
        from PyQt6.QtGui import QPainter, QPen, QFont
        from PyQt6.QtCore import QRectF
        if THEME == "glass":
            paint_glass(self)
        elif THEME == "aero":
            paint_sky(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if THEME not in ("glass", "aero"):
            p.fillRect(self.rect(), QColor(FILM))
        ink, soft, accent = (QColor(G_INK), QColor(G_SOFT), QColor(G_VIOLET)) if THEME == "glass" \
            else (QColor("#1C1B33"), QColor("#6E7090"), QColor(DYELINE))
        # the turning ring
        ring = QRectF(18, 20, 30, 30)
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 45), 4))
        p.drawEllipse(ring)
        pen = QPen(accent, 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(ring, -self.angle * 16, 100 * 16)
        # title and how many
        f = QFont()
        f.setFamilies(["Inter Display", "Adwaita Sans", "Inter", "Cantarell"])
        f.setPointSizeF(13)
        f.setWeight(QFont.Weight.ExtraBold)
        p.setFont(f)
        p.setPen(ink)
        p.drawText(QRectF(60, 16, self.width() - 70, 22), Qt.AlignmentFlag.AlignVCenter, "FileUzi")
        f.setPointSizeF(8)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(soft)
        p.drawText(QRectF(60, 37, self.width() - 70, 16), Qt.AlignmentFlag.AlignVCenter, self.subtitle)
        # steps done (newest last, up to four), then the current one
        y = 66
        fm = p.fontMetrics()
        for text in self.done[-4:]:
            p.setPen(QColor(46, 160, 110))
            p.drawText(QRectF(20, y, 14, 16), Qt.AlignmentFlag.AlignVCenter, "✓")
            p.setPen(soft)
            p.drawText(QRectF(36, y, self.width() - 52, 16), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(text, Qt.TextElideMode.ElideRight, self.width() - 56))
            y += 17
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(accent)
        dots = "." * (1 + (self.angle // 40) % 3)
        p.drawText(QRectF(20, y, 14, 16), Qt.AlignmentFlag.AlignVCenter, "›")
        p.setPen(ink)
        p.drawText(QRectF(36, y, self.width() - 52, 16), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(self.current + dots, Qt.TextElideMode.ElideRight, self.width() - 56))
        p.end()


class SharePopup(QFrame):
    """Floats over the email text when the email has a share link (WeTransfer,
    Dropbox...): buttons to open the link in your browser, and a zone to drop
    the downloaded files (or the .zip) onto. ✕ folds it to a small pill; the
    whole card still takes dropped files."""
    dropped = pyqtSignal(list)

    def __init__(self, parent):
        super().__init__(parent)
        from PyQt6.QtWidgets import QToolButton
        self.setObjectName("Share")
        self.setAcceptDrops(True)
        self.folded, self.links = False, []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 8, 8)
        lay.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.title = QLabel()
        self.title.setObjectName("ShareTitle")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("ShareClose")
        self.close_btn.setText("✕")
        self.close_btn.setToolTip("Fold this away (you can still drop files on the card)")
        self.close_btn.clicked.connect(lambda: self.fold(True))
        top.addWidget(self.title, 1)
        top.addWidget(self.close_btn)
        lay.addLayout(top)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(5)
        lay.addLayout(self.buttons)
        self.zone = QLabel()
        self.zone.setObjectName("ShareZone")
        self.zone.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zone.setWordWrap(True)
        lay.addWidget(self.zone)
        self.pill = QPushButton(parent)
        self.pill.setObjectName("SharePill")
        self.pill.clicked.connect(lambda: self.fold(False))
        self.pill.setAcceptDrops(True)
        self.pill.hide()
        self.hide()

    def show_links(self, links, added=0, busy=False):
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        self.links = links
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        names = list(dict.fromkeys(n for n, _ in links))
        self.title.setText(f"{' and '.join(names[:2])} link in this email" if len(names) <= 2
                           else f"{len(links)} share links in this email")
        for name, url in links[:2]:
            b = QPushButton(f"Open {name}" if len(links) == 1 or names.count(name) == 1 else "Open link")
            b.setObjectName("ShareOpen")
            b.setToolTip(url)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            self.buttons.addWidget(b)
        self.buttons.addStretch(1)
        if busy:
            self.zone.setText("Adding the files…")
        elif added:
            self.zone.setText(f"{added} file{'s' if added != 1 else ''} added. Drop more here")
        else:
            self.zone.setText("Drop the downloads (or the .zip) here")
        self.pill.setText(f"🔗 {names[0]}" + (f" · {added} added" if added else " · drop files"))
        self.place()
        self.fold(self.folded)

    def fold(self, folded):
        self.folded = folded
        self.setVisible(not folded)
        self.pill.setVisible(folded)
        if not folded:
            self.raise_()
        else:
            self.pill.raise_()

    def place(self):
        """Over the lower part of the email text (top-right corner when folded)."""
        letter = self.parent().letter
        r = letter.geometry()
        tl = letter.mapTo(self.parent(), letter.rect().topLeft())
        h = min(r.height() - 8, max(self.sizeHint().height(), 92))
        self.setGeometry(tl.x() + 4, tl.y() + r.height() - h - 4, r.width() - 8, h)
        self.pill.adjustSize()
        self.pill.move(tl.x() + r.width() - self.pill.width() - 8, tl.y() + 6)

    def hide_all(self):
        self.hide()
        self.pill.hide()

    @staticmethod
    def local_files(event):
        md = event.mimeData()
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []

    def dragEnterEvent(self, e):
        if self.local_files(e):
            self.zone.setProperty("drop", True)
            self.zone.style().unpolish(self.zone)
            self.zone.style().polish(self.zone)
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.zone.setProperty("drop", False)
        self.zone.style().unpolish(self.zone)
        self.zone.style().polish(self.zone)

    def dropEvent(self, e):
        self.dragLeaveEvent(e)
        files = self.local_files(e)
        if files:
            e.acceptProposedAction()
            self.dropped.emit(files)


class DoneOverlay(QWidget):
    """The marker between emails: veil, white disc, ring sweep, tick draws,
    a small burst, 'Filed' and the description, then fades to the next email.
    play() calls on_cover once the card is hidden, so the next email can be
    swapped in underneath."""
    LENGTH_MS = 1150
    COVER_AT = 0.30                                        # fully veiled by now

    def __init__(self, parent):
        super().__init__(parent)
        self.t, self.title, self.detail, self.on_cover, self.manual = 0.0, "", "", None, False
        self.hold_check, self.holding, self.phase = None, False, 0
        self.dots = QTimer(self)
        self.dots.timeout.connect(self.tick_dots)
        self.hide()

    def tick_dots(self):
        self.phase = (self.phase + 1) % 4
        self.update()

    def release(self):
        """The next item is ready: finish the fade."""
        if self.holding:
            self.holding = False
            self.dots.stop()
            self.anim.resume()

    def play(self, title, detail, on_cover, note=""):
        from PyQt6.QtCore import QVariantAnimation, QEasingCurve
        self.title, self.detail, self.on_cover, self.note = title, detail, on_cover, note
        self.setGeometry(self.parent().rect())
        self.raise_()
        self.show()
        self.set_t(0.0)
        if self.manual:                                    # (frame-by-frame, for the video)
            return
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(self.LENGTH_MS)
        self.anim.setEasingCurve(QEasingCurve.Type.Linear)
        self.anim.valueChanged.connect(self.set_t)
        self.anim.finished.connect(self.hide)
        self.anim.start()

    HOLD_AT = 0.78                                         # 'Filed' fully shown, before the fade

    def set_t(self, t):
        t = float(t)
        if self.on_cover and t >= self.COVER_AT:           # swap the next item in first, even if a
            cb, self.on_cover = self.on_cover, None        # busy machine skipped frames past it
            cb()
            self.raise_()
        if (not self.manual and self.t < self.HOLD_AT <= t and self.hold_check
                and self.hold_check()):
            self.t = self.HOLD_AT                          # next one isn't ready: wait here
            self.holding = True
            self.anim.pause()
            self.dots.start(380)
            self.update()
            return
        self.t = t
        if self.t >= 1.0:
            self.hide()
        self.update()

    @staticmethod
    def span(t, a, b):
        return max(0.0, min(1.0, (t - a) / (b - a)))

    def paintEvent(self, e):
        import math
        from PyQt6.QtCore import QPointF, QRectF
        from PyQt6.QtGui import QConicalGradient, QPainter, QPainterPath, QPen, QBrush, QRadialGradient
        t, w, h = self.t, self.width(), self.height()
        ease_out = lambda x: 1 - (1 - x) ** 3
        back_out = lambda x: 1 + 2.2 * (x - 1) ** 3 + 1.2 * (x - 1) ** 2   # a little overshoot
        a, b, veil, ink, soft = {
            "glass": ("#6A5AE0", "#F0688A", QColor(246, 244, 253), QColor(G_INK), QColor(G_SOFT)),
            "aero": ("#1F86D4", "#52C941", QColor(236, 247, 255), QColor(AERO_INK), QColor(AERO_SOFT)),
        }.get(THEME, (DYELINE, DYELINE, QColor(FILM), QColor(GRAPHITE), QColor(LEAD)))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fade_in, fade_out = self.span(t, 0.0, 0.16), 1 - self.span(t, 0.82, 1.0)
        p.setOpacity(fade_in * fade_out)
        veil.setAlpha(255)                                 # solid: no ghost of the old email
        p.fillRect(self.rect(), veil)
        glow = QRadialGradient(QPointF(w / 2, h * 0.42), max(w, h) * 0.6)
        g1 = QColor(a)
        g1.setAlpha(60)
        glow.setColorAt(0, g1)
        glow.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(self.rect(), QBrush(glow))

        c = QPointF(w / 2, h * 0.40)
        R = min(w, h) * 0.17 * back_out(self.span(t, 0.04, 0.34))
        if R > 0:
            shadow = QColor(a)
            shadow.setAlpha(45)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(shadow)
            p.drawEllipse(QPointF(c.x(), c.y() + R * 0.12), R * 1.04, R * 1.04)
            p.setBrush(QColor("white"))
            p.drawEllipse(c, R, R)
            # ring sweeping round
            sweep = ease_out(self.span(t, 0.12, 0.48))
            if sweep > 0:
                ring = QConicalGradient(c, 90)
                ring.setColorAt(0, QColor(a))
                ring.setColorAt(0.5, QColor(b))
                ring.setColorAt(1, QColor(a))
                pen = QPen(QBrush(ring), max(2.5, R * 0.11))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(QRectF(c.x() - R * 0.86, c.y() - R * 0.86, R * 1.72, R * 1.72),
                          90 * 16, int(-360 * 16 * sweep))
            # the tick, drawn in one stroke
            draw = ease_out(self.span(t, 0.34, 0.62))
            if draw > 0:
                pts = [QPointF(c.x() - R * 0.36, c.y() + R * 0.02), QPointF(c.x() - R * 0.10, c.y() + R * 0.28),
                       QPointF(c.x() + R * 0.40, c.y() - R * 0.26)]
                path = QPainterPath(pts[0])
                path.lineTo(pts[1])
                path.lineTo(pts[2])
                part = QPainterPath(pts[0])
                steps = 24
                for k in range(1, int(steps * draw) + 1):
                    part.lineTo(path.pointAtPercent(k / steps))
                part.lineTo(path.pointAtPercent(draw))
                tick = QPen(QColor(a), max(3.0, R * 0.16))
                tick.setCapStyle(Qt.PenCapStyle.RoundCap)
                tick.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(tick)
                p.drawPath(part)
            # a small burst as the tick lands
            q = self.span(t, 0.52, 0.86)
            if 0 < q < 1 and not self.holding:
                p.setPen(Qt.PenStyle.NoPen)
                for k in range(8):
                    ang = math.radians(k * 45 + 22.5)
                    dist = R * (1.15 + 0.55 * ease_out(q))
                    dot = QColor(a if k % 2 else b)
                    dot.setAlpha(int(255 * (1 - q)))
                    p.setBrush(dot)
                    p.drawEllipse(QPointF(c.x() + math.cos(ang) * dist, c.y() + math.sin(ang) * dist),
                                  R * 0.07, R * 0.07)

        # words
        words = self.span(t, 0.50, 0.70)
        if words > 0:
            p.setOpacity(fade_in * fade_out * words)
            lift = (1 - ease_out(words)) * 6
            f = QFont(self.font())
            f.setFamilies(["Inter Display", "Adwaita Sans", "Inter", "Cantarell"])
            f.setWeight(QFont.Weight.ExtraBold)
            f.setPointSizeF(13)
            p.setFont(f)
            p.setPen(ink)
            top = c.y() + min(w, h) * 0.17 + 18 + lift
            p.drawText(QRectF(0, top, w, 24), int(Qt.AlignmentFlag.AlignHCenter), self.title)
            f.setPointSizeF(8.5)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(soft)
            fm = p.fontMetrics()
            lines, line = [], ""
            for word in self.detail.split():               # wrap onto at most 2 lines
                trial = (line + " " + word).strip()
                if fm.horizontalAdvance(trial) > w - 40 and line:
                    lines.append(line)
                    line = word
                else:
                    line = trial
            lines.append(line)
            if len(lines) > 2:
                lines = [lines[0], fm.elidedText(" ".join(lines[1:]), Qt.TextElideMode.ElideRight, w - 40)]
            for n, text in enumerate(lines):
                p.drawText(QRectF(20, top + 26 + n * 15, w - 40, 16), int(Qt.AlignmentFlag.AlignHCenter), text)
            if self.holding:                               # waiting for the next email
                p.setPen(soft)
                p.drawText(QRectF(20, h - 46, w - 40, 16), int(Qt.AlignmentFlag.AlignHCenter),
                           "Opening the next one" + "." * self.phase)
            if getattr(self, "note", ""):                  # e.g. '1 older drawing to Superseded'
                p.setPen(QColor(a))
                p.drawText(QRectF(20, top + 30 + len(lines) * 15, w - 40, 16),
                           int(Qt.AlignmentFlag.AlignHCenter), "↻ " + self.note)
        p.end()


ANIMATE_TICK = True        # the tick card between emails (False = straight to the next one)


class Panel(QWidget):
    ready = pyqtSignal()                                   # the first card is ready to show
    want_plan = pyqtSignal(int)
    want_replan = pyqtSignal(int, object, str)
    want_file = pyqtSignal(int, object, object)

    def __init__(self, fz, emails, modes=None):
        super().__init__()
        self.fz, self.emails = fz, emails
        self.modes = modes or ["email"] * len(emails)
        self.revealed = False
        self.plans, self.requested, self.current = {}, set(), 0
        self.done, self.filing, self.skipped, self.results = 0, 0, 0, []
        self.tally, self.result_index = {}, []           # what each filing took, for the end card
        self.warnings = []
        self.undo_stack = []
        self.setObjectName("Panel")
        self.setWindowTitle("FileUzi")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(STYLE)
        self.group_ids = itertools.count(1)
        self.build()
        self.share = SharePopup(self)
        self.share.dropped.connect(self.add_dropped)
        self.setAcceptDrops(True)                          # files can be dropped anywhere on the card
        self.overlay = DoneOverlay(self)
        self.overlay.hold_check = lambda: (self.current < len(self.emails) and self.current not in self.plans)
        self.set_compact(True)

        # Two background workers: one reads emails ahead of you, the other files
        # and redoes 'Also to' at once, without queueing behind the reading.
        self.thread = QThread(self)
        self.worker = Worker(fz, emails, self.modes)
        self.worker.moveToThread(self.thread)
        self.want_plan.connect(self.worker.plan)
        self.worker.planned.connect(self.on_planned)
        self.worker.status.connect(self.on_status)
        self.file_thread = QThread(self)
        self.filer = Worker(fz, emails, self.modes)
        self.filer.moveToThread(self.file_thread)
        self.want_replan.connect(self.filer.replan_also)
        self.want_file.connect(self.filer.file)
        self.filer.replanned.connect(self.on_replanned)
        self.filer.filed.connect(self.on_filed)
        self.filer.status.connect(self.on_filing_status)
        self.thread.start()
        self.file_thread.start()
        self.request(0)
        self.show_waiting()

    # --- layout ---
    def build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.progress = Segments(len(self.emails))

        body = QVBoxLayout()
        body.setContentsMargins(20, 12, 20, 16)
        body.setSpacing(8)
        self.body = body
        root.addLayout(body)

        top = QHBoxLayout()
        self.counter = QLabel()
        self.counter.setObjectName("Status")
        self.status = QLabel()
        self.status.setObjectName("Status")
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.counter)
        top.addWidget(self.progress, 1, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.status)
        top.setSpacing(8)
        body.addLayout(top)

        self.banner = QLabel()
        self.banner.setObjectName("Banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        self.banner.mousePressEvent = lambda e: self.banner.hide()
        body.addWidget(self.banner)

        self.subject = QLabel()
        self.subject.setObjectName("Subject")
        self.subject.setWordWrap(True)
        self.meta = QLabel()
        self.meta.setObjectName("Meta")
        self.meta.setWordWrap(True)
        for label in (self.subject, self.meta):            # long text never widens the card
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setMinimumWidth(0)
        body.addWidget(self.subject)
        body.addWidget(self.meta)

        self.letter = QTextBrowser()
        self.letter.setObjectName("Letter")
        self.letter.setOpenLinks(False)
        self.letter.setMinimumHeight(90)
        self.letter.setMaximumHeight(170)
        body.addWidget(self.letter)
        soft_shadow(self.letter)

        # title block
        body.addSpacing(6)
        tb = QFrame()
        tb.setObjectName("TitleBlock")
        grid = QGridLayout(tb)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        self.job = QLineEdit()
        self.job.setObjectName("Job")
        self.job.setFixedWidth(70)
        self.dir = QPushButton("IN")
        self.dir.setObjectName("Dir")
        self.dir.setFixedWidth(48)
        self.dir.setToolTip("Click to switch between IN and OUT")
        self.dir.clicked.connect(self.flip_direction)
        self.date = QDateEdit()
        self.date.setDisplayFormat("dd-MM-yyyy")
        self.date.setMinimumDate(QDate(2000, 1, 1))
        self.date.setSpecialValueText(" ")                  # blank while the next email is read
        self.date.setCalendarPopup(True)
        self.date.setFixedWidth(118)
        self.who = QComboBox()
        self.readable_list(self.who)
        self.who.setEditable(True)
        self.desc = DescBox()
        c_job, _ = cell("Job", self.job)
        c_dir, _ = cell("In / out", self.dir)
        c_date, _ = cell("Date", self.date)
        c_who, self.who_label = cell("From", self.who, "CellLast")
        c_desc, _ = cell("Description", self.desc, "CellWide")
        self.cells, self.grid = (c_job, c_dir, c_date, c_who, c_desc), grid
        self.cell_tags = [c.findChild(QLabel, "CellLabel") for c in self.cells]
        # one line from the email, for the small card
        self.key = QLabel()
        self.key.setObjectName("Key")
        self.key.setWordWrap(True)
        body.addWidget(self.key)
        body.addWidget(tb)
        soft_shadow(tb)
        self.tb = tb
        self.folder_name = QLabel()
        self.folder_name.setObjectName("FolderName")
        self.folder_name.setWordWrap(True)
        self.folder_name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self.folder_name)
        for w in (self.who, self.desc):
            w.editTextChanged.connect(self.update_name)
        for edit in (self.job, self.who.lineEdit()):
            edit.installEventFilter(self)
        self.desc.edit.viewport().installEventFilter(self)
        self.job.textChanged.connect(self.update_name)
        self.job.editingFinished.connect(self.job_changed)
        self.date.dateChanged.connect(self.update_name)

        self.plan_line = QLabel()
        self.plan_line.setObjectName("Plan")
        self.plan_line.setWordWrap(True)
        self.plan_line.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        body.addWidget(self.plan_line)

        # each file in the email, and the folders it goes to
        self.files_head = None                   # (headings are rows in the tree)
        self.extract_head = None
        self.extract = QListWidget()
        self.extract.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.extract.setMaximumHeight(150)
        self.extract.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.extract.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        body.addWidget(self.extract)
        self.extract.hide()                     # (replaced by the tree below)
        self.show_all = QCheckBox()             # (kept so older code paths still work)
        self.show_all.hide()
        self.also_hint = QLabel()
        self.also_hint.setObjectName("Hint")
        self.also_hint.setWordWrap(True)
        body.addWidget(self.also_hint)
        self.also = QTreeWidget()               # file, with its folders underneath
        self.also.setColumnCount(1)
        self.also.setHeaderHidden(True)
        self.also.setRootIsDecorated(False)
        self.also.setIndentation(18)
        self.also.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.also.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.also.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.also.setUniformRowHeights(False)
        self.also.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(self.also, 1)
        self.also.hide()                        # (replaced by the cards below)
        self.cards = QScrollArea()
        self.cards.setObjectName("Cards")
        self.cards.setWidgetResizable(True)
        self.cards.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("CardsInner")
        self.cards_box = QVBoxLayout(inner)
        self.cards_box.setContentsMargins(0, 0, 0, 0)
        self.cards.setWidget(inner)
        body.addWidget(self.cards, 1)
        self.summary = QLabel()
        self.summary.setObjectName("Summary")
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.hide()
        body.addWidget(self.summary, 1)

        # footer
        foot = QHBoxLayout()
        self.last = QLabel()
        self.last.setObjectName("Hint")
        self.last.setWordWrap(True)
        self.last.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.skip = QPushButton("Skip this email")
        self.skip.setObjectName("Quiet")
        self.go = QPushButton("File email")
        self.go.setObjectName("Primary")
        self.go.setDefault(True)
        soft_shadow(self.go, (240, 104, 138, 110), 16, 4)
        self.skip.clicked.connect(self.on_skip)
        self.go.clicked.connect(self.on_file)
        self.more = QPushButton("Details")
        self.more.setObjectName("Link")
        self.more.setToolTip("Show everything: attachments, every folder, the whole email")
        self.more.clicked.connect(lambda: self.set_compact(not self.compact))
        self.page = 0
        self.back_btn = QPushButton("‹")
        self.back_btn.setObjectName("Arrow")
        self.back_btn.setToolTip("Back to the email (Alt+Left)")
        self.back_btn.clicked.connect(lambda: self.flick(0))
        self.next_btn = QPushButton("⌄")              # one arrow, flips between the two pages
        soft_shadow(self.skip, (70, 60, 160, 35), 12, 3)
        self.next_btn.setObjectName("Arrow")
        soft_shadow(self.next_btn, (110, 125, 235, 110), 12, 3)
        self.next_btn.setToolTip("Files and where they go (Alt+Down)")
        self.next_btn.clicked.connect(lambda: self.flick(1 - self.page))
        foot.addWidget(self.back_btn)
        foot.addWidget(self.more)
        foot.addWidget(self.last, 1)
        foot.addWidget(self.skip)
        foot.addWidget(self.go)
        foot.addWidget(self.next_btn)
        QShortcut(QKeySequence("Alt+Down"), self, activated=lambda: self.flick(1))
        QShortcut(QKeySequence("Alt+Up"), self, activated=lambda: self.flick(0))
        self.extract.itemChanged.connect(self.update_plan_line)

        body.addSpacing(4)
        body.addLayout(foot)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.on_file)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo)    # Ctrl+Z: the cards (text boxes keep their own)

    def eventFilter(self, obj, event):
        """First click into Job / name / description selects it all: type to
        replace. A second click puts the cursor where you click."""
        from PyQt6.QtCore import QEvent
        if obj.property("drag_src") is not None or obj.property("drop_key") is not None:
            if self.drag_events(obj, event):
                return True
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(obj, QLineEdit) and not obj.hasFocus():
            obj.setFocus(Qt.FocusReason.MouseFocusReason)
            QTimer.singleShot(0, obj.selectAll)
            return True
        if (event.type() == QEvent.Type.MouseButtonPress and obj is self.desc.edit.viewport()
                and not self.desc.edit.hasFocus()):
            self.desc.edit.setFocus(Qt.FocusReason.MouseFocusReason)
            QTimer.singleShot(0, self.desc.edit.selectAll)
            return True
        return super().eventFilter(obj, event)

    # --- small card / full window ---
    FULL_SIZE, CARD_SIZE = (720, 920), (264, 375)      # roughly a third of the full window, plus room

    def set_compact(self, compact):
        self.compact = compact
        self.setProperty("compact", compact)
        c_job, c_dir, c_date, c_who, c_desc = self.cells
        g = self.grid
        for c in self.cells:
            g.removeWidget(c)
        if compact:                                    # Job | In/out | Date, then From, then Description
            g.addWidget(c_job, 0, 0); g.addWidget(c_dir, 0, 1); g.addWidget(c_date, 0, 2)
            g.addWidget(c_who, 1, 0, 1, 3); g.addWidget(c_desc, 2, 0, 1, 3)
            c_date.setObjectName("CellLast"); c_who.setObjectName("CellWide")
            g.setColumnStretch(3, 0); g.setColumnStretch(2, 1)
        else:                                          # one row, Description underneath
            g.addWidget(c_job, 0, 0); g.addWidget(c_dir, 0, 1); g.addWidget(c_date, 0, 2)
            g.addWidget(c_who, 0, 3); g.addWidget(c_desc, 1, 0, 1, 4)
            c_date.setObjectName("Cell"); c_who.setObjectName("CellLast")
            g.setColumnStretch(2, 0); g.setColumnStretch(3, 1)
        self.job.setFixedWidth(42 if compact else 70)
        self.dir.setFixedWidth(34 if compact else 48)
        self.date.setFixedWidth(90 if compact else 118)       # room for the whole year
        self.date.setCalendarPopup(not compact)
        self.body.setContentsMargins(*((10, 6, 10, 8) if compact else (20, 12, 20, 16)))
        self.body.setSpacing(5 if compact else 8)
        done = self.go.text() == "Close"
        self.letter.setMinimumHeight(70 if compact else 90)
        self.letter.setMaximumHeight(16777215 if compact else 170)
        self.key.hide()
        # card: no labels on Job / In-out / Date (obvious), label beside From and Description
        for i, (c, tag) in enumerate(zip(self.cells, self.cell_tags)):
            lay = c.layout()
            lay.setDirection(lay.Direction.LeftToRight if compact else lay.Direction.TopToBottom)
            lay.setContentsMargins(*((6, 1, 6, 1) if compact else (8, 4, 8, 5)))
            lay.setSpacing(6 if compact else 0)
            if i == 4:                                 # Description keeps its label on top
                lay.setDirection(lay.Direction.TopToBottom)
                lay.setSpacing(0)
            tag.setVisible(not compact or i >= 3)
            if compact and i == 3:
                tag.setFixedWidth(30)
            elif compact:
                tag.setMinimumWidth(0)
                tag.setMaximumWidth(16777215)
            else:
                tag.setMinimumWidth(0)
                tag.setMaximumWidth(16777215)
        self.elide_subject()
        self.skip.setText("Skip" if compact else "Skip this email")
        if not done:
            self.go.setText("File" if compact else "File email")
        self.more.setText("Details" if compact else "Less")
        self.apply_view()
        self.setStyleSheet(STYLE)                      # re-apply for the [compact] rules
        QTimer.singleShot(0, self.desc.fit)
        QTimer.singleShot(0, self.steady)
        self.setMinimumSize(0, 0)
        if getattr(self, "meta_texts", None) and self.go.text() != "Close":
            self.set_meta(self.meta_texts[0 if compact else 1])
        self.resize(*(self.CARD_SIZE if compact else self.FULL_SIZE))
        self.update_name()

    def apply_view(self):
        """Card page 1: the email and its title block. Card page 2: what comes
        out and where else it goes. Full window: everything at once."""
        compact, page = self.compact, getattr(self, "page", 0)
        done = self.go.text() == "Close"
        mode = self.mode() if self.current < len(self.emails) else "email"
        if mode == "check":                                # one page: the fix cards
            page = 0
        email = not done and (not compact or page == 0) and mode != "check"
        filing = not done and (not compact or page == 1 or mode == "check")
        self.letter.setVisible(email)
        no_job = not (self.plans.get(self.current) or {}).get("job")
        self.tb.setVisible(email and (mode != "also" or no_job))
        self.plan_line.setVisible(compact and email and mode != "check")
        self.folder_name.setVisible(not compact and not done)
        for w in [self.cards] + self.findChildren(QLabel, "Section"):
            w.setVisible(filing)
        self.also_hint.setVisible(filing and (not compact or getattr(self, "no_suggestions", False)
                                              or mode == "check"))
        self.last.setVisible(not compact and not done)
        self.next_btn.setVisible(compact and not done and mode != "check")
        self.next_btn.setText("⌃" if page else "⌄")
        self.next_btn.setStyleSheet("padding: 6px 0 0 0;" if page else "padding: 0 0 7px 0;")  # centre the glyph
        self.next_btn.setToolTip("Back to the email (Alt+Up)" if page else "Files and where they go (Alt+Down)")
        self.back_btn.hide()
        self.more.setVisible(not compact and not done)       # 'Less' only, in the big window
        if compact and not done and mode != "check":         # filing is decided on the files page
            self.go.setText("Next" if page == 0 else {"also": "Copy"}.get(mode, "File"))
            self.go.setToolTip("See the files and where they go" if page == 0 else "")


    def settle(self):
        """After the layout has caught up: card size, and the email text
        scrolled to the 'please find attached' sentence."""
        if self.compact:
            self.resize(*self.CARD_SIZE)
        self.letter.scrollToAnchor("key")
        if self.share.isVisible() or self.share.pill.isVisible():
            self.share.place()

    def flick(self, page):
        """The arrow: card page 1 <-> page 2 for the same email."""
        if not self.compact or self.go.text() == "Close":
            return
        self.page = page
        self.apply_view()
        self.share_view()
        QTimer.singleShot(30, self.settle)
        self.go.setFocus()

    def set_meta(self, text):
        """The line under the subject: one line on the card (cut with '…'), so the
        card keeps its shape from one email to the next."""
        self.meta_full = text
        self.meta.setWordWrap(not self.compact)
        if self.compact:
            self.meta.setText(self.meta.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight,
                                                                 self.CARD_SIZE[0] - 22))
            self.meta.setToolTip(text)
        else:
            self.meta.setText(text)

    def steady(self):
        """Fixed heights for the parts that would otherwise change size per email."""
        if self.compact:
            self.plan_line.ensurePolished()
            self.plan_line.setFixedHeight(self.plan_line.fontMetrics().lineSpacing() * 2 + 2)
        else:
            self.plan_line.setMinimumHeight(0)
            self.plan_line.setMaximumHeight(16777215)

    def elide_subject(self):
        """Card: subject on one line, cut with '…'. Full window: wrapped in full."""
        if getattr(self, "meta_full", None) is not None:
            self.set_meta(self.meta_full)
        full = getattr(self, "subject_full", None)
        if full is None:
            return
        self.subject.setWordWrap(not self.compact)
        if self.compact:
            width = self.CARD_SIZE[0] - 22
            self.subject.setText(self.subject.fontMetrics().elidedText(full, Qt.TextElideMode.ElideRight, width))
        else:
            self.subject.setText(full)

    def update_plan_line(self, *_):
        """'3 files and a PDF of the email. Also to Current Drawings and 1 more.'"""
        plan = self.plans.get(self.current)
        if not plan or plan.get("skip") or plan.get("error"):
            self.plan_line.setText("")
            return
        c = self.choices()
        mode = plan.get("mode", "email")
        if mode == "check":
            self.plan_line.setText("")
            return
        n = len(c["rows"])
        take = (f"{n} file{'s' if n != 1 else ''}" if n else "") + \
               (" + email PDF" if c["pdf"] and n else "email PDF" if c["pdf"] else "")
        names = list(dict.fromkeys(short_folder(rel, title=True) for rel, _, _ in c["routes"]))
        also = ("Also to " + names[0] + (f" +{len(names) - 1}" if len(names) > 1 else "")
                if names else "Nowhere else")
        if mode != "email":
            also = also.replace("Also to", "Copies to") if names else "No copies"
        sup = self.superseded_count(c)
        sup_text = f" {sup} superseded." if sup else ""
        self.plan_line.setText((f"Takes {take or 'nothing'}. " if mode == "email" else "") + f"{also}.{sup_text}")

    def superseded_list(self, rel, names, notes=None):
        """Files in a Current Drawings folder that these drawings would replace."""
        plan = self.plans.get(self.current) or {}
        also, src = plan.get("also") or {}, self.src_dir(plan)
        if not (src and also.get("job_root") and rel.upper().endswith("CURRENT-DRAWINGS")):
            return []
        mine = {n for n in names if n in also.get("mine", ())}
        try:
            older, _, _ = self.fz.supersede_plan(Path(src), also["job_root"] / rel, mine, notes)
        except Exception:
            return []
        return [f.name for f in older]

    def superseded_count(self, c):
        return len({old for rel, _, files in c.get("routes", []) for old in self.superseded_list(rel, files)})

    # --- what the item on screen is ---
    WORDS = {"email": "Email", "in": "Folder", "out": "Folder", "also": "Folder", "check": "Check"}

    def mode(self, i=None):
        i = self.current if i is None else i
        return self.modes[i] if 0 <= i < len(self.modes) else "email"

    def counter_text(self, i):
        kinds = set(self.modes)
        word = self.WORDS.get(self.mode(i), "Item") if len(kinds) == 1 else "Item"
        return f"{word} {i + 1} of {len(self.emails)}"

    def src_dir(self, plan):
        """Where the files are now: the private staging copy (email) or the folder."""
        return plan.get("staging") or plan.get("folder")

    # --- loading ---
    def request(self, i):
        if 0 <= i < len(self.emails) and i not in self.requested:
            self.requested.add(i)
            self.want_plan.emit(i)

    def reveal(self):
        """The first time there's a real card (or the end): the start-up card gives way."""
        if not self.revealed:
            self.revealed = True
            self.ready.emit()

    def blank_card(self, subject, meta, body=""):
        """Same shape, none of the previous email's details: used while the next
        one is being read, and for items with nothing to file."""
        self.subject_full = subject
        self.subject.setToolTip(subject)
        self.elide_subject()
        self.set_meta(meta)
        self.key.hide()
        self.letter.setHtml(f'<div style="color:{LEAD}">{html.escape(body)}</div>' if body else "")
        self.share.hide_all()
        self.job.setText("")
        self.dir.setText("")
        self.date.setDate(self.date.minimumDate())
        self.who.clear()
        self.desc.clear()
        self.plan_line.setText("")

    def show_waiting(self):
        self.go.setEnabled(False)
        self.skip.setEnabled(False)
        self.counter.setText(self.counter_text(self.current))
        self.page = 0
        self.apply_view()
        self.blank_card({"email": "Reading the next email", "check": "Checking drawings"}
                        .get(self.mode(), "Reading the next folder"),
                        {"email": "One moment…", "check": "Looking through the job…"}
                        .get(self.mode(), "Looking at the folder…"))

    def on_status(self, text):
        self.status.setText(text)

    def on_planned(self, i, plan):
        self.plans[i] = plan
        if i == self.current:
            self.show_email(i)
        self.top_up()

    @staticmethod
    def nothing_to_do(plan):
        return bool(plan.get("skip") and not plan.get("share_links") and not plan.get("error"))

    def top_up(self, ahead=5):
        """Keep five emails WITH something to file read and ready ahead of you.
        Emails with nothing to file don't count, so a run of them doesn't
        leave the reader idle."""
        real, j = 0, self.current + 1
        while real < ahead and j < len(self.emails):
            plan = self.plans.get(j)
            if plan is None:
                self.request(j)                            # (pending ones count as real until known)
                real += 1
            elif not self.nothing_to_do(plan):
                real += 1
            j += 1

    def on_replanned(self, i, plan):
        if i == self.current:
            self.fill_files(plan)
            self.update_plan_line()
            self.go.setEnabled(True)

    # --- showing an email ---
    def show_email(self, i):
        plan = self.plans[i]
        fz = self.fz
        QTimer.singleShot(0, self.overlay.release)
        self.counter.setText(self.counter_text(i))
        self.progress.setCurrent(i)
        self.top_up()                                     # get the next two ready meanwhile
        self.page = 0                                     # every email starts on the email page
        self.apply_view()
        if plan.get("skip") and plan.get("share_links") and not plan.get("error"):
            self.blank_card(plan.get("parsed", {}).get("subject") or plan["eml"].name,
                            "Nothing attached, but there's a share link",
                            "Open the link, download the files, then drop them on this card. "
                            "Or skip it.")
            self.go.setEnabled(False)
            self.skip.setEnabled(True)
            self.share_view()
            QTimer.singleShot(60, self.settle)             # place the pop-up once the layout has settled
            self.reveal()
            return
        if self.nothing_to_do(plan):                       # no attachments: no card, straight on
            self.log(f"Left {plan['eml'].name} where it is. {plan['skip']}")
            self.results.append({"name": plan["eml"].name, "ok": False, "note": True, "lines": [plan["skip"]]})
            self.result_index.append(i)
            self.skipped += 1
            QTimer.singleShot(0, self.advance)
            return
        if plan.get("error"):
            note = plan["error"]
            self.blank_card(plan.get("parsed", {}).get("subject") or plan["eml"].name,
                            "Couldn't read this one, moving on…", note)
            self.go.setEnabled(False)
            self.skip.setEnabled(False)
            self.log(f"Left {plan['eml'].name} where it is. {note}")
            self.results.append({"name": plan["eml"].name, "ok": False, "note": True, "lines": [note]})
            self.result_index.append(i)
            self.skipped += 1
            QTimer.singleShot(1400, self.advance)          # say so, then move on
            self.reveal()
            return
        if plan.get("mode") == "check":
            return self.show_check(plan)
        p = plan["parsed"]
        self.subject_full = p["subject"]
        self.subject.setToolTip(p["subject"])
        self.elide_subject()
        when = plan["when"]
        if plan.get("mode", "email") == "email":
            frm = fz.person(p["from"])
            self.meta_texts = (f"{frm[:1].upper() + frm[1:]} to {fz.person(p['to'])}, {when:%a %d %b}",
                               f"From {fz.person(p['from'])} to {fz.person(p['to'])}, {when:%A %d %B %Y}")
            self.letter.setHtml(self.letter_html(plan))
        else:
            n, dates = len(plan["atts"]), plan.get("file_dates") or []
            odd = ""
            if dates and dates != [plan["made"]]:            # files dated differently: say so, don't ask
                odd = (f", files dated {dates[0]:%d %b}" if len(dates) == 1
                       else f", files dated {dates[0]:%d %b} to {dates[-1]:%d %b}")
            self.meta_texts = (f"Made {plan['made']:%a %d %b}, {n} file{'s' if n != 1 else ''}{odd}",
                               f"Folder made {plan['made']:%A %d %B %Y}, {n} file{'s' if n != 1 else ''}{odd}")
            self.letter.setHtml(self.folder_html(plan))
        self.set_meta(self.meta_texts[0 if self.compact else 1])


        self.job.setText(plan["job"])
        self.set_direction(plan["direction"])
        self.date.setDate(QDate(when.year, when.month, when.day))
        self.who.clear()
        self.who.addItems(plan["who_options"])
        self.desc.clear()
        self.desc.addItems(plan["desc_options"])
        self.desc.setToolTip(self.desc.currentText())
        self.who.lineEdit().setCursorPosition(0)

        self.fill_files(plan)
        self.apply_view()
        QTimer.singleShot(60, self.settle)
        self.update_name()
        self.update_plan_line()
        self.go.setEnabled(True)
        self.skip.setEnabled(True)
        self.go.setFocus()
        self.share_view()
        self.reveal()

    # --- share links: open in the browser, drop the downloads on the card ---
    def share_view(self):
        """The share-link pop-up: on the email page of an email that has one."""
        plan = self.plans.get(self.current) or {}
        links = plan.get("share_links")
        done = self.go.text() == "Close"
        if links and not done and self.mode() == "email" and getattr(self, "page", 0) == 0 \
                and self.current < len(self.emails):
            added = sum(1 for a in plan.get("atts") or [] if a.get("dropped"))
            self.share.show_links(links, added=added)
        else:
            self.share.hide_all()

    def add_dropped(self, files):
        i = self.current
        plan = self.plans.get(i)
        if self.go.text() == "Close" or not plan or self.mode() != "email" or self.overlay.isVisible():
            return
        old = self.worker.extra.get(i, [])
        new = [f for f in files if f not in old]
        if not new:
            return
        self.worker.extra[i] = old + new
        if plan.get("share_links"):
            self.share.show_links(plan["share_links"], busy=True)
        self.log(f"Adding {len(new)} dropped item{'s' if len(new) != 1 else ''}…")
        self.go.setEnabled(False)
        self.fz.drop_staging(plan)
        del self.plans[i]                                  # read it again, with the files
        self.want_plan.emit(i)

    def dragEnterEvent(self, e):
        if SharePopup.local_files(e) and self.mode() == "email" and self.go.text() != "Close":
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = SharePopup.local_files(e)
        if files:
            e.acceptProposedAction()
            self.add_dropped(files)

    def folder_html(self, plan):
        """A folder's contents, where the email text would be."""
        seen = plan.get("seen_as", {})
        rows = []
        for a in plan["atts"]:
            kb = a["size"] / 1024
            size = f"{kb / 1024:.1f} MB" if kb > 1024 else f"{kb:.0f} KB"
            note = f" <i>(page 1 looks like {html.escape(seen[a['name']])})</i>" if a["name"] in seen else ""
            rows.append(f"{html.escape(a['name'])} <span style='color:{LEAD}'>{size}</span>{note}")
        return f'<div style="line-height:145%">{"<br>".join(rows)}</div>'

    def show_check(self, plan):
        """Check Drawings: one card per drawing that needs attention."""
        issues = plan["issues"]
        self.subject_full = f"Check drawings: {plan['root'].name}"
        self.subject.setToolTip(self.subject_full)
        self.elide_subject()
        warns = sum(1 for x in issues if x["warns"])
        self.meta_texts = (f"{plan['drawings']} of your drawings, {len(issues)} to look at",
                           f"{plan['drawings']} of your drawings found, {plan['in_current']} in Current Drawings. "
                           f"{len(issues)} to look at" + (f", {warns} with warnings" if warns else "") + ".")
        self.set_meta(self.meta_texts[0 if self.compact else 1])
        self.also_hint.setText("Everything matches what was last issued." if not issues else
                               "Ticked fixes are applied. Warnings start unticked: the issue dates on your "
                               "OUT folders are treated as the truth.")
        if plan.get("create_current"):
            self.also_hint.setText(f"There's no {plan['current'].name} folder yet. Fixing creates it and "
                                   "puts the last issued copy of each drawing in it.")
        self.rows, self.groups, self.taken = [], [], set()
        self.render_check(plan)
        self.apply_view()
        QTimer.singleShot(60, self.settle)
        self.go.setText("Fix" if issues else "Done")
        self.go.setEnabled(True)
        self.skip.setEnabled(True)
        self.go.setFocus()
        self.reveal()

    def render_check(self, plan):
        box = self.cards_box
        while box.count():
            item = box.takeAt(0)
            if item.widget():
                old = item.widget()
                old.hide()
                old.setParent(None)
                old.deleteLater()
        self.card_widgets, self.fix_ticks = {}, []
        box.setSpacing(6 if self.compact else 8)
        words = {"missing": "Not in Current", "behind": "Out of date", "duplicate": "Older revision left in",
                 "changed": "Different from what was issued", "warning": "Check the revisions",
                 "note": "PL / P mix-up", "stray": "Two superseded folders"}
        for n, issue in enumerate(plan["issues"]):
            card, lay = self.card("Group", words.get(issue["kind"], issue["kind"]))
            card.setProperty("tone", "2" if issue["warns"] else str(n % 2))
            tick = QCheckBox("Fix")
            tick.setObjectName("FixTick")
            tick.setChecked(issue["ticked"])
            tick.setEnabled(bool(issue["actions"]))
            tick.toggled.connect(lambda *_: self.update_plan_line())
            lay.itemAt(0).layout().insertWidget(1, tick)
            self.fix_ticks.append(tick)
            head = QLabel()
            head.setObjectName("GroupFolder")
            head.setText(self.elided(head, issue["label"], self.text_width() + 10))
            head.setToolTip("\n".join(issue["files"]))
            lay.addWidget(head)
            for text in issue["lines"]:
                lab = QLabel(text)
                lab.setObjectName("GroupFile")
                lab.setWordWrap(True)
                lay.addWidget(lab)
            for text in issue["warns"]:
                lab = QLabel("⚠ " + text)
                lab.setObjectName("Warn")
                lab.setWordWrap(True)
                lay.addWidget(lab)
            for text in issue.get("notes", []):
                lab = QLabel("ℹ " + text)
                lab.setObjectName("SupNote")
                lab.setWordWrap(True)
                lay.addWidget(lab)
            if issue["actions"]:
                does = []
                for action, path in issue["actions"]:
                    does.append(f"copy in {self.fz.rev_code(path.name)}" if action == "copy"
                                else f"move its files across, then remove {path.name}" if action == "merge"
                                else f"{self.fz.rev_code(path.name)} superseded")
                lab = QLabel("Fix: " + ", ".join(does))
                lab.setObjectName("SupNote")
                lab.setWordWrap(True)
                lab.setToolTip("\n".join(f"{a}: {p}" for a, p in issue["actions"]))
                lay.addWidget(lab)
            box.addWidget(card)
        box.addStretch()

    def letter_html(self, plan):
        text, key = plan.get("quote") or "", plan.get("quote_key")
        body = html.escape(text)
        if key:
            pattern = r"\s+".join(re.escape(html.escape(w)) for w in key.split())
            mark = {"aero": "#C6EBFF", "glass": "#ECE8FF"}.get(THEME, DYELINE_PALE)
            body = re.sub(pattern, lambda m: f'<a name="key"></a><span style="background:{mark}">'
                                             f'{m.group(0)}</span>', body, count=1)
        body = body.replace("\n", "<br>") or f'<span style="color:{LEAD}">No message text.</span>'
        return f'<div style="line-height:145%">{body}</div>'

    # Page 2 is a stack of cards. The first is what comes out of the email (into
    # the new dated folder). Each card after it is a GROUP: some files, and the
    # folders those files are copied to. Suggestions arrive already grouped.

    def fill_files(self, plan):
        fz = self.fz
        also = plan.get("also") or {}
        self.also_ok = bool(also.get("job_root"))
        rows = []
        if plan["big_embedded"]:
            n = len(plan["big_embedded"])
            what = ", ".join(plan.get("content_seen") or []) or "sketches or screenshots"
            rows.append({"key": "PDF of the email", "name": fz.PDF_ROW, "is_pdf": True,
                         "detail": f"{n} image{'s' if n > 1 else ''} in the body ({what})", "omitted": None})
        seen_as = plan.get("seen_as", {})
        for a in plan["atts"]:
            kb = a["size"] / 1024
            size = f"{kb / 1024:.1f} MB" if kb > 1024 else f"{kb:.0f} KB"
            extra = f", page 1 looks like {seen_as[a['name']]}" if a["name"] in seen_as else ""
            rows.append({"key": a["row"], "name": a["name"], "is_pdf": False, "detail": size + extra,
                         "omitted": a["why"] if fz.is_branding(a) else None})
        self.rows = rows
        self.taken = {r["name"] for r in rows if not r["omitted"]}
        self.groups = []
        self.undo_stack = []
        if self.also_ok:                                   # files with the same suggestions share a card
            by = {}
            for r in rows:
                if r["omitted"]:
                    continue
                # a folder that doesn't exist yet isn't suggested, except Current
                # Drawings (shown as '(new)' and made when you file)
                dests = tuple(rel for rel in also["options"]
                              if r["name"] in also["dest_files"].get(rel, ())
                              and rel not in also["broken"]
                              and (rel not in also["missing"] or rel.upper().endswith("CURRENT-DRAWINGS")))
                for rel in dests:                          # one card per destination
                    by.setdefault(rel, []).append(r["name"])
            self.groups = [{"files": files, "folders": [self.new_folder_entry(rel)]}
                           for rel, files in by.items()]
        plan["suggested_routes"] = [(f[0], f[1], set(g["files"])) for g in self.groups for f in g["folders"]]
        self.no_suggestions = self.also_ok and not self.groups
        if not self.also_ok:
            self.also_hint.setText(also.get("warning") or "Add the job number to see where these could go.")
        elif self.no_suggestions:
            self.also_hint.setText("No suggestions. Use “+ New group” to copy files somewhere.")
        else:
            self.also_hint.setText(f"{also['job_root'].name}. Each group's files are copied to its folders. "
                                   "Nothing is ever overwritten.")
        self.render_cards()

    def new_folder_entry(self, rel):
        """[rel, typed name or None]: Surveys / Key-stage folders get a name."""
        also = self.plans[self.current]["also"]
        if rel in also.get("keystage", {}):
            rule = also["keystage"][rel]
            if not self.fz.is_keystage(rule):
                return [rel, ""]                           # Surveys: '' = same name as the IN/OUT folder
            default, _ = self.fz.subfolder_default(also["job_root"], rel, rule,
                                                   also["job"], self.desc.currentText())
            return [rel, default]
        return [rel, None]

    def label_for(self, name):
        return next((r["key"] for r in self.rows if r["name"] == name), name)

    def text_width(self):
        """Room for a file name inside a card."""
        return (self.CARD_SIZE[0] - 78) if self.compact else (self.FULL_SIZE[0] - 110)

    def elided(self, widget, text, width):
        widget.ensurePolished()
        return widget.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, width)

    def render_cards(self, grow=None, pulse=None):
        """Rebuild the cards from self.rows / self.taken / self.groups.
        grow: id of a group card to open smoothly; pulse: id of a card to glow
        (where dropped files landed)."""
        box = self.cards_box
        while box.count():
            item = box.takeAt(0)
            if item.widget():
                old = item.widget()
                old.hide()                                 # gone at once, not when Qt gets round to it
                old.setParent(None)
                old.deleteLater()
        self.card_widgets = {}
        self.lit = None
        if not getattr(self, "rows", None):
            return
        plan = self.plans.get(self.current) or {}
        also = plan.get("also") or {}
        box.setSpacing(6 if self.compact else 8)
        for g in self.groups:                              # stable ids for animation and dragging
            g.setdefault("id", next(self.group_ids))

        # the first card: what comes out of the email
        folder_mode = (plan.get("mode") or "email") != "email"
        renaming = plan.get("mode") in ("in", "out")
        base, lay = self.card("Base", "Renamed to" if renaming else "In this folder" if folder_mode
                              else "New folder", target="base")
        self.base_title = None
        self.base_head = base.findChild(QLabel, "CardTitle")
        if not folder_mode or renaming:                    # 'New IMPORT folder' + the description, editable here too
            self.base_title = DescBox()
            self.base_title.edit.setObjectName("FolderTitleEdit")
            self.base_title.addItems(self.desc.items)
            self.base_title.setText(self.desc.currentText())
            self.base_title.editTextChanged.connect(self.base_desc_changed)
            QTimer.singleShot(0, self.base_title.fit)
            lay.addWidget(self.base_title)
        for r in self.rows if folder_mode else []:
            lab = QLabel()
            lab.setObjectName("Take")
            lab.setText(self.elided(lab, r["key"], self.text_width() + 10))
            lab.setToolTip(f"{r['key']}\n{r['detail']}\nDrag onto a group to copy it there")
            self.make_draggable(lab, "base", r["name"])
            lay.addWidget(lab)
        for r in [] if folder_mode else self.rows:
            tick = QCheckBox()
            tick.setObjectName("Take")
            tick.setProperty("omitted", bool(r["omitted"]))
            tick.setText(self.elided(tick, r["key"], self.text_width() + 10))
            tick.setToolTip(f"{r['key']}\n" + (f"Not filed: {r['omitted']}" if r["omitted"] else r["detail"])
                            + "\nDrag onto a group to copy it there too")
            tick.setChecked(r["name"] in self.taken)
            tick.toggled.connect(lambda on, n=r["name"]: self.set_taken(n, on))
            if r["name"] in self.taken:
                self.make_draggable(tick, "base", r["name"])
            lay.addWidget(tick)
        box.addWidget(base)
        self.card_widgets["base"] = base

        # one card per group still being edited: its files, then where they're copied
        live = [g for g in self.groups if not g.get("accepted")]
        for n, g in enumerate(live):
            gid = g["id"]
            # the card is headed by where it goes: '→ CURRENT-DRAWINGS  ✓ ✕'
            card, lay = self.card("Group", "", accept=lambda gid=gid: self.accept_group(gid), target=gid)
            head_row = lay.itemAt(0).layout()
            head = card.findChild(QLabel, "CardTitle")
            folders = g["folders"]
            if folders:
                head.setObjectName("GroupHead")
                head.setText(self.elided(head, "→ " + self.folder_label(folders[0][0]), self.text_width() - 8))
                head.setToolTip(folders[0][0] + self.supersede_tip(folders[0][0], g["files"]))
                x = QPushButton("✕")
                x.setObjectName("X")
                x.setToolTip("Don't copy these here (removes the card)")
                x.clicked.connect(lambda _=False, gid=gid: self.drop_folder(gid, 0))
                head_row.addWidget(x)
            else:
                head.setObjectName("Empty")
                head.setText("Choose a folder (+ folder)")
                x = QPushButton("✕")
                x.setObjectName("X")
                x.setToolTip("Remove this group")
                x.clicked.connect(lambda _=False, gid=gid: self.drop_group(gid))
                head_row.addWidget(x)
            head.style().unpolish(head)
            head.style().polish(head)
            after = []                                     # notes that go below the file list
            for fi, entry in enumerate(folders[:1]):          # one destination per card
                rel, typed = entry
                mix_notes = []
                replaced = self.superseded_list(rel, [nm for nm in g["files"] if nm in self.taken], mix_notes)
                if replaced:                               # say it on the card, not just in a tooltip
                    def code(nm):                          # '22_P01' (new style), '10A' (old style)
                        num, rev = (self.fz.parse_drawing(nm) or {}).get("drawing", ""), self.fz.rev_code(nm)
                        return rev if rev.startswith(num) else f"{num}_{rev}".strip("_")
                    codes = sorted(code(nm) for nm in replaced)
                    joined = codes[0] if len(codes) == 1 else ", ".join(codes[:-1]) + " & " + codes[-1]
                    sup = QLabel(f"↻ {joined} superseded")
                    sup.setObjectName("SupNote")
                    sup.setWordWrap(True)
                    sup.setToolTip("Moves to Superseded:\n" + "\n".join(replaced))
                    after.append(sup)
                if mix_notes:                              # PL/P swapped: settled by date
                    mix = QLabel("ℹ PL/P mix-up: going by date, the one filed now counts as newer")
                    mix.setObjectName("SupNote")
                    mix.setWordWrap(True)
                    mix.setToolTip("\n".join(mix_notes))
                    after.append(mix)
                if typed is not None:                      # name for a Surveys / Key-stage folder
                    _, existing = self.fz.subfolder_default(also["job_root"], rel, also["keystage"][rel],
                                                            also["job"])
                    name_box = QComboBox()
                    name_box.setEditable(True)
                    name_box.addItems([typed] + [e for e in existing if e != typed])
                    name_box.lineEdit().setCursorPosition(0)
                    if typed == "":                        # Surveys
                        name_box.lineEdit().setPlaceholderText("Same name as the IN/OUT folder")
                        name_box.setToolTip("Left blank, the folder takes the IN/OUT folder's name "
                                            "(with _1 if that's taken). Or type / pick another.")
                    else:
                        name_box.setToolTip("Name of the folder to create, or pick an existing one")
                    self.narrow(name_box)
                    self.readable_list(name_box)
                    name_box.editTextChanged.connect(lambda t, entry=entry: entry.__setitem__(1, t))
                    lay.addWidget(name_box)
            # then the files going there
            if not g["files"]:
                lay.addWidget(self.empty("Drag files here, or + file"))
            for name in g["files"]:
                row, lab = self.line("GroupFile", self.label_for(name),
                                     lambda gid=gid, nm=name: self.drop_file(gid, nm),
                                     left=name not in self.taken,
                                     tip=f"{self.label_for(name)}\nDrag to move this group's files to another "
                                         "group. Ctrl+drag moves just this file.")
                self.make_draggable(lab, gid, name)
                lay.addLayout(row)
            for note in after:                             # '↻ 22_P01 & 23_P01 superseded' under the files
                lay.addWidget(note)
            row = QHBoxLayout()
            row.setSpacing(4)
            row.addWidget(self.picker("+ file", [(self.label_for(r["name"]), r["name"]) for r in self.rows
                                                 if r["name"] in self.taken and r["name"] not in g["files"]],
                                      lambda nm, gid=gid: self.add_to_group(gid, file=nm)), 1)
            row.addWidget(self.picker("change folder" if g["folders"] else "+ folder",
                                      [(rel, rel) for rel in also.get("options", [])
                                       if rel not in also.get("broken", ())
                                       and rel not in [f[0] for f in g["folders"]]],
                                      lambda rel, gid=gid: self.add_to_group(gid, folder=rel)), 1)
            lay.addLayout(row)
            box.addWidget(card)
            self.card_widgets[gid] = card

        if self.also_ok:
            new = QPushButton("+ New group")
            new.setObjectName("Link")
            new.setToolTip("Another set of files going to another folder. Drop files here to start one.")
            new.clicked.connect(self.new_group)
            self.make_target(new, "new")
            box.addWidget(new, 0, Qt.AlignmentFlag.AlignLeft)

        # accepted groups: out of the way, still filed, one tap to bring back
        done = [g for g in self.groups if g.get("accepted")]
        if done:
            strip, lay = self.card("Accepted", "Accepted")
            for g in done:
                files = [n for n in g["files"] if n in self.taken]
                where = ", ".join(re.sub(rf"^{re.escape(also.get('job', ''))}[_ -]+", "", short_folder(f[0]))
                                  for f in g["folders"]) or "no folder"
                row = QHBoxLayout()
                row.setSpacing(4)
                lab = QLabel()
                lab.setObjectName("AcceptedLine")
                lab.setText(self.elided(lab, f"✓ {len(files)} file{'s' if len(files) != 1 else ''} → {where}",
                                        self.text_width()))
                lab.setToolTip("\n".join(self.label_for(n) for n in files) + "\n→ " +
                               "\n→ ".join(f[0] for f in g["folders"]))
                back = QPushButton("↺")
                back.setObjectName("X")
                back.setToolTip("Bring this group back to edit")
                back.clicked.connect(lambda _=False, gid=g["id"]: self.restore_group(gid))
                row.addWidget(lab, 1)
                row.addWidget(back)
                lay.addLayout(row)
            box.addWidget(strip)
            self.card_widgets["accepted"] = strip
        box.addStretch()
        self.update_plan_line()
        self.update_name()
        if grow is not None and grow in self.card_widgets:
            QTimer.singleShot(0, lambda: self.grow_in(self.card_widgets.get(grow)))
        if pulse is not None and pulse in self.card_widgets:
            QTimer.singleShot(0, lambda: self.pulse(self.card_widgets.get(pulse)))

    def card(self, kind, title, remove=None, accept=None, target=None):
        frame = QFrame()
        frame.setObjectName(kind)
        if kind == "Group":                                # each group its own colour
            frame.setProperty("tone", str(len([1 for i in range(self.cards_box.count())
                                               if isinstance(self.cards_box.itemAt(i).widget(), QFrame)
                                               and self.cards_box.itemAt(i).widget().objectName() == "Group"]) % 3))
            soft_shadow(frame, (110, 90, 220, 70), 18, 5)
        else:
            soft_shadow(frame)
        if target is not None:
            self.make_target(frame, target)
        lay = QVBoxLayout(frame)
        m = 6 if self.compact else 10
        lay.setContentsMargins(m, m - 2, m, m)
        lay.setSpacing(2 if self.compact else 4)
        head = QHBoxLayout()
        head.setSpacing(4)
        t = QLabel(title)
        t.setObjectName("CardTitle")
        head.addWidget(t, 1)
        if accept:
            ok = QPushButton("✓")
            ok.setObjectName("Accept")
            ok.setToolTip("Looks good: tuck this group away (it will still be filed)")
            ok.clicked.connect(accept)
            head.addWidget(ok)
        if remove:
            x = QPushButton("✕")
            x.setObjectName("X")
            x.setToolTip("Remove this group (these files won't be copied here)")
            x.clicked.connect(remove)
            head.addWidget(x)
        lay.addLayout(head)
        return frame, lay

    def folder_label(self, rel):
        """'2505_ADMIN/2505_D_CONTRACT_ADMIN' -> 'D_CONTRACT_ADMIN', '(new)' if not made yet."""
        also = (self.plans.get(self.current) or {}).get("also") or {}
        shown = re.sub(rf"^{re.escape(also.get('job', ''))}[_ -]+", "", short_folder(rel)) or rel
        return shown + ("  (new)" if rel in also.get("missing", ()) else "")

    def empty(self, text):
        lab = QLabel(text)
        lab.setObjectName("Empty")
        return lab

    def line(self, kind, text, remove, left=False, tip=None):
        row = QHBoxLayout()
        row.setSpacing(4)
        lab = QLabel()
        lab.setObjectName(kind)
        lab.setProperty("left", left)
        lab.setText(self.elided(lab, text, self.text_width()))
        lab.setToolTip((tip or text) + ("\nLeft in the email, so not copied" if left else ""))
        x = QPushButton("✕")
        x.setObjectName("X")
        x.setToolTip("Take out of this group")
        x.clicked.connect(lambda _=False: remove())        # (clicked passes a bool: don't let it in)
        row.addWidget(lab, 1)
        row.addWidget(x)
        return row, lab

    # --- dragging files between cards ---
    MIME = "application/x-fileuzi-files"

    def make_draggable(self, widget, src, name):
        widget.setProperty("drag_src", src)
        widget.setProperty("drag_name", name)
        widget.setCursor(Qt.CursorShape.OpenHandCursor)
        widget.installEventFilter(self)

    def make_target(self, widget, key):
        widget.setProperty("drop_key", key)
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)

    def drag_events(self, obj, event):
        """Press and move on a file starts a drag; cards light up as drop targets.
        Returns True when the event was handled here."""
        from PyQt6.QtCore import QEvent, QMimeData
        from PyQt6.QtGui import QDrag
        kind = event.type()
        src = obj.property("drag_src")
        if src is not None and kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = (obj, event.position().toPoint())
            return False
        if (src is not None and kind == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton
                and getattr(self, "drag_start", None) and self.drag_start[0] is obj
                and (event.position().toPoint() - self.drag_start[1]).manhattanLength()
                >= QApplication.startDragDistance()):
            self.drag_start = None
            name = obj.property("drag_name")
            one = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier) or src == "base"
            group = self.group_by_id(src)
            files = [name] if one or group is None else list(group["files"])
            if isinstance(obj, QCheckBox):
                obj.setDown(False)                         # a drag isn't a tick
            drag = QDrag(obj)
            mime = QMimeData()
            mime.setData(self.MIME, json.dumps({"src": src, "files": files}).encode())
            drag.setMimeData(mime)
            drag.setPixmap(self.drag_pill(files))
            drag.setHotSpot(drag.pixmap().rect().center())
            self.dragging_from = src
            drag.exec(Qt.DropAction.MoveAction)
            self.dragging_from = None
            self.light(None)
            return True
        key = obj.property("drop_key")
        if key is None:
            return False
        if kind in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if event.mimeData().hasFormat(self.MIME) and key != getattr(self, "dragging_from", None):
                event.acceptProposedAction()
                self.light(obj)
            else:
                event.ignore()
            return True
        if kind == QEvent.Type.DragLeave:
            self.light(None)
            return True
        if kind == QEvent.Type.Drop:
            self.light(None)
            data = json.loads(bytes(event.mimeData().data(self.MIME)).decode())
            event.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.drop_files(data["src"], data["files"], key))
            return True
        return False

    def drag_pill(self, files):
        """The little label that follows the pointer: '3 files' or the file name."""
        from PyQt6.QtGui import QLinearGradient, QPainter, QPixmap
        text = f"{len(files)} files" if len(files) > 1 else self.label_for(files[0])
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold)
        f.setPointSizeF(8.5)
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        text = fm.elidedText(text, Qt.TextElideMode.ElideMiddle, 180)
        w, h = fm.horizontalAdvance(text) + 24, fm.height() + 10
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, w, 0)
        g.setColorAt(0, QColor("#6A5AE0"))
        g.setColorAt(1, QColor("#F0688A"))
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)
        p.setPen(QColor("white"))
        p.setFont(f)
        p.drawText(pm.rect().adjusted(0, 0, int(-w * (dpr - 1)), int(-h * (dpr - 1))),
                   int(Qt.AlignmentFlag.AlignCenter), text)
        p.end()
        return pm

    def light(self, widget):
        """Highlight the card under the pointer while dragging."""
        old = getattr(self, "lit", None)
        if old is widget:
            return
        for w, on in ((old, False), (widget, True)):
            if w is not None:
                try:
                    w.setProperty("drop", on)
                    w.style().unpolish(w)
                    w.style().polish(w)
                except RuntimeError:                       # (card already redrawn)
                    pass
        self.lit = widget

    def group_by_id(self, gid):
        return next((g for g in self.groups if g.get("id") == gid), None)

    def drop_files(self, src, files, target):
        self.remember()
        """Files dropped on a card:
        group -> group: they move (the source pops away if left empty)
        email card -> group: copied into that group as well
        anything -> '+ New group': a new group with those files
        group -> email card: taken out of the group (still go into the new folder)."""
        source = self.group_by_id(src)
        files = [f for f in files if f in self.taken]
        if not files:
            return
        emptied = None
        if target == "new":
            g = {"files": list(files), "folders": [], "id": next(self.group_ids)}
            self.groups.append(g)
            dest_id = g["id"]
        elif target == "base":
            dest_id = "base"
        else:
            dest = self.group_by_id(target)
            if dest is None or dest is source:
                return
            dest["files"] += [f for f in files if f not in dest["files"]]
            dest_id = dest["id"]
        if source is not None:                             # a move, not a copy
            source["files"] = [f for f in source["files"] if f not in files]
            if not source["files"]:
                emptied = source
        if emptied is not None:                            # pop the empty card, then redraw
            self.pop(self.card_widgets.get(emptied["id"]),
                     lambda: (self.groups.remove(emptied),
                              self.render_cards(grow=dest_id if target == "new" else None,
                                                pulse=None if target == "new" else dest_id)))
        else:
            self.render_cards(grow=dest_id if target == "new" else None,
                              pulse=None if target == "new" else dest_id)

    # --- animation ---
    def pop(self, widget, then):
        """Card fades and folds away; the cards below glide up into its place."""
        from PyQt6.QtCore import QPropertyAnimation, QParallelAnimationGroup, QEasingCurve
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        if widget is None:
            then()
            return
        fade = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(fade)
        h = widget.height()
        widget.setMinimumHeight(0)
        anims = QParallelAnimationGroup(self)
        a1 = QPropertyAnimation(fade, b"opacity", anims)
        a1.setDuration(200)
        a1.setStartValue(1.0)
        a1.setEndValue(0.0)
        a1.setEasingCurve(QEasingCurve.Type.InQuad)
        a2 = QPropertyAnimation(widget, b"maximumHeight", anims)
        a2.setDuration(280)
        a2.setStartValue(h)
        a2.setEndValue(0)
        a2.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anims.addAnimation(a1)
        anims.addAnimation(a2)
        anims.finished.connect(then)
        self.anims = anims
        anims.start()

    def grow_in(self, widget):
        """A new card opens out from nothing."""
        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
        if widget is None:
            return
        h = widget.sizeHint().height()
        widget.setMaximumHeight(0)
        a = QPropertyAnimation(widget, b"maximumHeight", self)
        a.setDuration(260)
        a.setStartValue(0)
        a.setEndValue(h)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.finished.connect(lambda: widget.setMaximumHeight(16777215))
        self.grow_anim = a
        a.start()
        QTimer.singleShot(60, lambda: self.cards.ensureWidgetVisible(widget))

    def pulse(self, widget):
        """Where dropped files landed: the card's glow swells and settles."""
        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
        fx = widget.graphicsEffect() if widget is not None else None
        if fx is None or not hasattr(fx, "blurRadius"):
            return
        a = QPropertyAnimation(fx, b"blurRadius", self)
        a.setDuration(520)
        a.setKeyValueAt(0, fx.blurRadius())
        a.setKeyValueAt(0.35, fx.blurRadius() + 26)
        a.setKeyValueAt(1, fx.blurRadius())
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.pulse_anim = a
        a.start()

    def picker(self, label, items, chosen):
        box = QComboBox()
        box.setObjectName("Picker")
        box.addItem(label)
        for text, value in items:
            box.addItem(text, value)
        box.setEnabled(bool(items))
        self.narrow(box)
        self.readable_list(box)

        def picked(i):
            if i > 0:
                value = box.itemData(i)
                QTimer.singleShot(0, lambda: chosen(value))
        box.activated.connect(picked)
        return box

    def readable_list(self, box):
        """The open list draws with its own colours, not the button's (on the blue
        group cards the button text is white, which made the list white on white)."""
        from PyQt6.QtWidgets import QStyledItemDelegate
        from PyQt6.QtGui import QPalette

        class Roomy(QStyledItemDelegate):
            def sizeHint(self, option, index):
                size = super().sizeHint(option, index)
                size.setHeight(max(size.height(), option.fontMetrics.height()) + 8)
                return size
        box.setItemDelegate(Roomy(box))
        view = box.view()
        pal = view.palette()
        for role, colour in ((QPalette.ColorRole.Base, "#FFFFFF"), (QPalette.ColorRole.Text, "#1C1B33"),
                             (QPalette.ColorRole.Window, "#FFFFFF"), (QPalette.ColorRole.WindowText, "#1C1B33"),
                             (QPalette.ColorRole.Highlight, "#6A5AE0"),
                             (QPalette.ColorRole.HighlightedText, "#FFFFFF")):
            pal.setColor(role, QColor(colour))
        view.setPalette(pal)
        view.setStyleSheet("QAbstractItemView { background: #FFFFFF; color: #1C1B33; border: 1px solid #D9D4FF;"
                           " selection-background-color: #6A5AE0; selection-color: #FFFFFF; outline: 0; }"
                           "QAbstractItemView::item { color: #1C1B33; padding: 3px 6px; min-height: 18px; }"
                           "QAbstractItemView::item:selected, QAbstractItemView::item:hover"
                           " { background: #6A5AE0; color: #FFFFFF; }")
        view.window().setStyleSheet("background: #FFFFFF;")

    def narrow(self, box):
        """Drop-downs size to their longest folder path otherwise, pushing the
        card wider than the window."""
        box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        box.setMinimumContentsLength(4)
        box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        box.view().setMinimumWidth(min(420, max(self.width() - 20, 200)))   # the open list can be wider

    def supersede_tip(self, rel, names):
        older = self.superseded_list(rel, names)
        return ("\nMoves " + ", ".join(older) + " to Superseded") if older else ""

    # --- group edits (by id; removals animate) ---
    def remember(self):
        """Before any change to the cards: a copy for Ctrl+Z (last 30 changes, this email only)."""
        import copy
        self.undo_stack.append((copy.deepcopy(self.groups), set(self.taken)))
        del self.undo_stack[:-30]

    def undo(self):
        if not self.undo_stack or self.overlay.isVisible() or self.go.text() == "Close":
            return
        self.groups, self.taken = self.undo_stack.pop()
        self.render_cards()
        self.toast("Undone")

    def set_taken(self, name, on):
        self.remember()
        (self.taken.add if on else self.taken.discard)(name)
        QTimer.singleShot(0, self.render_cards)

    def add_to_group(self, gid, file=None, folder=None):
        self.remember()
        g = self.group_by_id(gid)
        if g is None:
            return
        if file and file not in g["files"]:
            g["files"].append(file)
        if folder and folder not in [f[0] for f in g["folders"]]:
            g["folders"] = [self.new_folder_entry(folder)]  # one destination per card
        self.render_cards(pulse=gid)

    def drop_file(self, gid, name):
        self.remember()
        self.toast("File taken out. Ctrl+Z to undo")
        g = self.group_by_id(gid)
        if g is None:
            return
        g["files"].remove(name)
        if not g["files"] and g["folders"]:
            self.pop(self.card_widgets.get(gid), lambda: (self.groups.remove(g), self.render_cards()))
        else:
            QTimer.singleShot(0, self.render_cards)

    def drop_folder(self, gid, fi):
        self.remember()
        self.toast("Folder removed. Ctrl+Z to undo")
        g = self.group_by_id(gid)
        if g is None:
            return
        if len(g["folders"]) == 1 and g["files"]:          # nowhere left to go: the card pops
            self.pop(self.card_widgets.get(gid), lambda: (self.groups.remove(g), self.render_cards()))
            return
        del g["folders"][fi]
        QTimer.singleShot(0, self.render_cards)

    def drop_group(self, gid):
        self.remember()
        self.toast("Group removed. Ctrl+Z to undo")
        g = self.group_by_id(gid)
        if g is not None:
            self.pop(self.card_widgets.get(gid), lambda: (self.groups.remove(g), self.render_cards()))

    def accept_group(self, gid):
        """✓: the card pops; the group is kept (and filed) in the Accepted strip."""
        self.remember()
        g = self.group_by_id(gid)
        if g is not None:
            self.pop(self.card_widgets.get(gid),
                     lambda: (g.__setitem__("accepted", True), self.render_cards(pulse="accepted")))

    def restore_group(self, gid):
        self.remember()
        g = self.group_by_id(gid)
        if g is not None:
            g["accepted"] = False
            self.render_cards(grow=gid)

    def new_group(self):
        self.remember()
        g = {"files": [], "folders": [], "id": next(self.group_ids)}
        self.groups.append(g)
        if self.no_suggestions:
            self.no_suggestions = False
            self.also_hint.setVisible(not self.compact)
        self.render_cards(grow=g["id"])

    def apply_filter(self):
        pass                                               # (every row is always shown now)

    # --- edits ---
    def set_direction(self, d):
        self.dir.setText(d)
        self.who_label.setText("From" if d == "IN" else "To")

    def flip_direction(self):
        self.set_direction("OUT" if self.dir.text() == "IN" else "IN")
        self.update_name()                                 # (also renames 'New IMPORT/EXPORT folder')

    def update_name(self):
        plan = self.plans.get(self.current)
        if not plan or plan.get("skip") or plan.get("error"):
            self.folder_name.setText("")
            return
        d = self.date.date()
        from datetime import date
        name = self.fz.email_folder_name(self.job.text().strip() or "????", self.dir.text(),
                                         date(d.year(), d.month(), d.day()),
                                         self.who.currentText() or "?", self.desc.currentText() or "?")
        mode = plan.get("mode", "email")
        title = getattr(self, "base_title", None)
        if title is not None:
            try:
                if mode in ("email", "in", "out"):        # 'New IMPORT folder' / 'New EXPORT folder'
                    kind = "IMPORT" if self.dir.text() == "IN" else "EXPORT"
                    self.base_head.setText(f"New {kind} folder" if mode == "email" else f"Renamed {kind} folder")
                    if not title.edit.hasFocus() and title.currentText() != self.desc.currentText():
                        title.setText(self.desc.currentText())     # front page edited: follow it
                    tip = (f"Made in {plan['eml'].parent.name}:\n" if mode == "email" else "Renamed to:\n") + name
                    title.setToolTip(tip)
                    self.base_head.setToolTip(tip)
            except RuntimeError:                           # (card already redrawn)
                pass
        self.folder_name.setText(f"Renamed to:  {name}" if mode in ("in", "out") else
                                 f"Copies from {plan['folder'].name}" if mode == "also" else
                                 f"New folder in {plan['eml'].parent.name}:  {name}")

    def base_desc_changed(self, text):
        """Edited on the files page: the front page (and the folder name) follow."""
        if text != self.desc.currentText():
            self.desc.setText(text)
            self.desc.setToolTip(text)

    def job_changed(self):
        plan = self.plans.get(self.current)
        job = self.fz.clean(self.job.text())
        if plan and not plan.get("skip") and job and job != (plan.get("also") or {}).get("job"):
            self.go.setEnabled(False)
            self.also_hint.setText(f"Looking for job {job}'s folders…")
            self.want_replan.emit(self.current, plan, job)

    # --- actions ---
    def choices(self):
        if self.mode() == "check":
            return {"fix": [i for i, t in enumerate(getattr(self, "fix_ticks", [])) if t.isChecked()],
                    "routes": [], "rows": set(), "pdf": False, "job": "", "who": "", "desc": "",
                    "direction": "", "when": None}
        taken = getattr(self, "taken", set())
        rows, pdf = set(), False
        for r in getattr(self, "rows", []):
            if r["name"] in taken:
                if r["is_pdf"]:
                    pdf = True
                else:
                    rows.add(r["key"])
        routes = []
        for g in getattr(self, "groups", []):
            files = {n for n in g["files"] if n in taken}   # left in the email = goes nowhere
            for rel, typed in g["folders"]:
                if files:
                    routes.append((rel, typed, files))
        d = self.date.date()
        from datetime import date
        return {"rows": rows, "pdf": pdf, "job": self.fz.clean(self.job.text()),
                "direction": self.dir.text(), "who": self.who.currentText().strip(),
                "desc": self.desc.currentText().strip(), "when": date(d.year(), d.month(), d.day()),
                "routes": routes}

    def on_file(self):
        if not self.go.isEnabled() or self.overlay.isVisible():
            return                                         # (no double filing while the tick plays)
        if self.compact and getattr(self, "page", 0) == 0 and self.mode() != "check":
            return self.flick(1)                           # 'Next': look at the files page first
        c = self.choices()
        mode = self.mode()
        if mode == "check":
            if not c["fix"]:
                self.skipped += 1                          # nothing ticked: just move on
                self.log("No fixes ticked, so nothing was changed.")
                return self.advance()
        else:
            need = (("job number", c["job"]),) if mode == "also" else \
                   (("job number", c["job"]), ("name", c["who"]), ("description", c["desc"]))
            missing = [n for n, v in need if not v]
            if missing:
                self.warn(f"Add the {' and '.join(missing)} first.")
                return
            if mode == "email" and not c["rows"] and not c["pdf"]:
                self.warn("Nothing is ticked to take out of the email. Tick something, or skip it.")
                return
            if mode == "also" and not c["routes"]:
                self.warn("Nothing to copy yet. Add a group, or skip this folder.")
                return
        self.banner.hide()
        self.filing += 1
        plan = self.plans[self.current]
        if mode == "email":
            files = len(c["rows"]) + (1 if c["pdf"] else 0)
        elif mode == "check":
            files = 0
        else:
            files = len(plan.get("atts") or [])
        self.tally[self.current] = {
            "mode": mode, "files": files, "fixes": len(c["fix"]) if mode == "check" else 0,
            "copies": sum(len(f) for _, _, f in c["routes"]),
            "superseded": self.superseded_count(c) if mode != "check" else 0}
        self.want_file.emit(self.current, plan, c)
        if mode == "check":
            self.log(f"Fixing {len(c['fix'])} drawing{'s' if len(c['fix']) != 1 else ''}…")
        elif mode == "also":
            self.log(f"Copying from {self.plans[self.current]['folder'].name}…")
        else:
            self.log(f"Filing {self.fz.email_folder_name(c['job'], c['direction'], c['when'], c['who'], c['desc'])}…")
        if ANIMATE_TICK:
            self.go.setEnabled(False)
            title = {"also": "Copied", "check": "Fixed"}.get(mode, "Filed")
            if mode == "check":
                n = len(c["fix"])
                detail = f"{n} drawing{'s' if n != 1 else ''} put right"
            else:
                detail = c["desc"] or self.plans[self.current]["folder"].name
            sup = self.superseded_count(c) if mode != "check" else 0
            note = f"{sup} older drawing{'s' if sup != 1 else ''} to Superseded" if sup else ""
            self.overlay.play(title, detail, self.advance, note)  # next item loads under the veil
        else:
            self.advance()

    def on_skip(self):
        if self.overlay.isVisible() or self.go.text() == "Close":
            return
        plan = self.plans.get(self.current)
        if plan:
            self.fz.drop_staging(plan)
            self.log(f"Skipped {plan['eml'].name}. It's still in the folder.")
            subject = (plan.get("parsed") or {}).get("subject") or plan["eml"].name
            self.toast(f"Skipped: {subject}")
        self.skipped += 1
        self.advance()

    def advance(self):
        self.progress.setValue(self.done + self.skipped)
        self.current += 1
        if self.current >= len(self.emails):
            self.finish()
            return
        self.letter.clear()
        self.extract.clear()
        self.also.clear()
        self.rows, self.groups = [], []
        self.render_cards()
        self.folder_name.setText("")
        if self.current in self.plans:
            self.show_email(self.current)
        else:
            self.show_waiting()
            self.request(self.current)

    def on_filed(self, i, result):
        if result.get("offer_email"):                       # a fresh OUT folder: offer the email
            QTimer.singleShot(200, lambda args=result["offer_email"]: self.safely(self.fz.offer_email, *args))
        self.filing -= 1
        self.done += 1
        self.progress.setValue(self.done + self.skipped)
        self.results.append(result)
        self.result_index.append(i)
        if result["ok"]:
            first = result["lines"][0].splitlines()[0] if result["lines"] else ""
            self.log(f"Filed {result['folder']}. {first}".strip())
            later = [l for l in result["lines"] if "NOT copied" in l or "Skipped" in l or "Couldn't" in l]
            if later:
                self.warn("\n".join(later))
        else:
            self.warn(f"{result['name']} wasn't filed. " + " ".join(result["lines"]))
        if self.current >= len(self.emails):
            if self.filing:
                self.set_meta(self.finishing_text())
            else:
                self.finish()

    def finish(self):
        self.reveal()
        QTimer.singleShot(0, self.overlay.release)
        self.counter.setText(f"{len(self.emails)} of {len(self.emails)}")
        self.progress.setValue(self.done + self.skipped)
        self.go.setEnabled(False)
        self.skip.setEnabled(False)
        if self.filing:
            self.finishing = True
            self.blank_card("Finishing off", self.finishing_text(),
                            "Filing the last ones in the background. You can leave this open; "
                            "it closes to the summary when they're done.")
            for w in (self.tb, self.plan_line, self.next_btn, self.skip):
                w.hide()
            self.go.setText("Filing…")
            QTimer.singleShot(0, self.settle)
            return
        self.blank_card("All done", "Current Drawings checked." if set(self.modes) == {"check"}
                        else f"{len(self.emails)} {self.item_word(len(self.emails))} gone through")
        self.apply_view()
        for w in [self.letter, self.tb, self.folder_name, self.extract, self.also, self.also_hint,
                  self.show_all, self.skip, self.cards] + self.findChildren(QLabel, "Section"):
            w.hide()
        self.last.setText("")
        self.banner.hide()
        self.summary.setText(self.stats_html())
        self.summary.show()
        self.key.hide()
        self.plan_line.hide()
        self.more.hide()
        self.go.setText("Close")
        self.apply_view()
        if self.compact:
            QTimer.singleShot(0, lambda: self.resize(*self.CARD_SIZE))
        self.go.setEnabled(True)
        self.go.clicked.disconnect()
        self.go.clicked.connect(self.close)
        self.go.setFocus()

    def finishing_text(self, step=""):
        total = self.done + self.filing
        return f"Filed {self.done} of {total}" + (f": {step.lower()}" if step else "…")

    def on_filing_status(self, text):
        if getattr(self, "finishing", False) and self.filing:
            self.set_meta(self.finishing_text(text.split(" (")[0] if text else ""))

    def toast(self, text, ms=1300):
        """A small note above the buttons that fades by itself (e.g. 'Skipped')."""
        if not hasattr(self, "toast_label"):
            self.toast_label = QLabel(self)
            self.toast_label.setObjectName("Toast")
            self.toast_timer = QTimer(self)
            self.toast_timer.setSingleShot(True)
            self.toast_timer.timeout.connect(self.toast_label.hide)
        lab = self.toast_label
        lab.setText(text)
        lab.adjustSize()
        lab.setMaximumWidth(self.width() - 40)
        lab.setText(lab.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, self.width() - 60))
        lab.adjustSize()
        lab.move((self.width() - lab.width()) // 2, self.go.mapTo(self, self.go.rect().topLeft()).y() - lab.height() - 8)
        lab.show()
        lab.raise_()
        self.toast_timer.start(ms)

    def item_word(self, n):
        kinds = set(self.modes or ["email"])
        word = "email" if kinds == {"email"} else "drawing check" if kinds == {"check"} else \
               "folder" if "email" not in kinds else "item"
        return word + ("s" if n != 1 else "")

    def stats_html(self):
        """The end card: a few numbers, and only the problems by name."""
        ok = [i for i, r in zip(self.result_index, self.results) if r["ok"]]
        t = [self.tally.get(i, {}) for i in ok]
        files = sum(x.get("files", 0) for x in t)
        copies = sum(x.get("copies", 0) for x in t)
        sup = sum(x.get("superseded", 0) for x in t)
        fixes = sum(x.get("fixes", 0) for x in t)
        rows = [(len(ok), f"{self.item_word(len(ok))} filed"),
                (self.skipped, "left where they were")]
        if files:
            rows.append((files, "files filed" if files != 1 else "file filed"))
        if copies:
            rows.append((copies, "copies to other folders" if copies != 1 else "copy to another folder"))
        if sup:
            rows.append((sup, "older drawings to Superseded" if sup != 1 else "older drawing to Superseded"))
        if fixes:
            rows.append((fixes, "drawings put right" if fixes != 1 else "drawing put right"))
        table = "".join(f'<tr><td align="right" style="padding:0 10px 5px 0"><b>{n}</b></td>'
                        f'<td style="padding-bottom:5px">{html.escape(label[:1].upper() + label[1:])}</td></tr>'
                        for n, label in rows)
        problems = [r for r in self.results if not r["ok"] and not r.get("note")]
        if problems:
            names = ", ".join(html.escape(r["name"]) for r in problems[:2])
            more = f" and {len(problems) - 2} more" if len(problems) > 2 else ""
            table += (f'<tr><td align="right" style="padding:6px 10px 0 0; color:{REDLINE}"><b>{len(problems)}</b></td>'
                      f'<td style="padding-top:6px; color:{REDLINE}">Not filed: {names}{more}</td></tr>')
        if self.warnings:
            n = len(self.warnings)
            table += (f'<tr><td align="right" style="padding:6px 10px 0 0; color:{LEAD}"><b>{n}</b></td>'
                      f'<td style="padding-top:6px; color:{LEAD}">Warning{"s" if n != 1 else ""} '
                      f'(hover here to read)</td></tr>')
            self.summary.setToolTip("\n\n".join(self.warnings))
        return f'<table cellspacing="0">{table}</table>'

    def safely(self, fn, *args):
        """An error in a side job (e.g. the email offer) shows in the banner
        instead of closing the window."""
        try:
            fn(*args)
        except Exception as e:
            self.warn(f"Couldn't finish that: {e}")

    # --- messages ---
    def log(self, text):
        self.last.setText(text)

    def warn(self, text):
        """A warning strip. On the card it's two lines at most (the card keeps its
        size); hover for the whole message. Each one is also counted on the end card."""
        self.warnings.append(text)
        self.banner.setToolTip(text)
        if self.compact:
            flat = " ".join(l.strip() for l in text.splitlines() if l.strip())
            self.banner.setText(flat if len(flat) <= 88 else flat[:85].rsplit(" ", 1)[0] + " …")
            self.banner.setMaximumHeight(self.banner.fontMetrics().lineSpacing() * 2 + 10)
        else:
            self.banner.setText(text)
            self.banner.setMaximumHeight(16777215)
        self.banner.show()
        QTimer.singleShot(0, self.settle)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "overlay"):
            self.overlay.setGeometry(self.rect())
        if hasattr(self, "share") and (self.share.isVisible() or self.share.pill.isVisible()):
            QTimer.singleShot(0, self.share.place)

    def paintEvent(self, e):
        if THEME == "aero":
            paint_sky(self)
        elif THEME == "glass":
            paint_glass(self)
        else:
            super().paintEvent(e)

    def closeEvent(self, e):
        for t in (self.thread, self.file_thread):
            t.quit()
        self.file_thread.wait(30000)                       # let a filing in progress finish
        self.thread.wait(3000)
        for plan in self.plans.values():
            self.fz.drop_staging(plan)
        super().closeEvent(e)


def run(fz, emails, modes=None):
    """Called by fileuzi_rename.py. Returns when the window is closed."""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationDisplayName("FileUzi")
    screen = app.primaryScreen().availableGeometry()
    splash = Splash(len(emails), (modes or ["email"])[0])
    splash.move(screen.right() - splash.width() - 24, screen.top() + 40)
    splash.show()
    app.processEvents()
    splash.step("Setting up the window")
    app.processEvents()
    panel = Panel(fz, emails, modes)
    panel.worker.status.connect(splash.step)

    def reveal():
        try:
            panel.worker.status.disconnect(splash.step)
        except TypeError:
            pass
        splash.spin.stop()
        splash.close()
        panel.move(screen.right() - panel.width() - 24, screen.top() + 40)
        panel.show()
    panel.ready.connect(reveal)

    # model warnings (e.g. 'not inside bubblewrap') show in the panel, not as
    # pop-ups; a signal carries them safely from the background thread
    class Bridge(QObject):
        note = pyqtSignal(str)
    bridge = Bridge()
    bridge.note.connect(panel.warn)
    original = fz.message

    def message(kind, text):
        if kind != "info":
            bridge.note.emit(text)
    fz.message = message
    if panel.revealed:                                     # (already had something to show)
        reveal()
    try:
        app.exec()
    finally:
        fz.message = original
