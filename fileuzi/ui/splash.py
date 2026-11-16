"""
Splash screen for FileUzi — logo fades to reveal loading progress.
"""
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap, QFont, QColor, QPainter

LOGO_PATH = Path(__file__).parent.parent.parent / "assets" / "fileuzi_logo.png"

SPLASH_BG = "#1a1a2e"
SPLASH_TEXT = "#e0e0e8"
SPLASH_ACCENT = "#6C63FF"
SPLASH_DIM = "#6e7090"


class SplashScreen(QWidget):
    """Full-window splash: logo fades down, status steps fade in below."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedSize(480, 520)
        self.setStyleSheet(f"background-color: {SPLASH_BG};")
        self._center_on_screen()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top section: logo
        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setStyleSheet("background: transparent;")
        if LOGO_PATH.exists():
            pixmap = QPixmap(str(LOGO_PATH)).scaled(
                320, 320,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.logo_label.setPixmap(pixmap)
        else:
            self.logo_label.setText("FileUzi")
            self.logo_label.setFont(QFont("", 36, QFont.Weight.Bold))
            self.logo_label.setStyleSheet(f"color: {SPLASH_TEXT}; background: transparent;")
        layout.addWidget(self.logo_label)

        # Status area
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFont(QFont("", 11))
        self.status_label.setStyleSheet(f"color: {SPLASH_DIM}; background: transparent; padding: 8px;")
        self.status_label.setFixedHeight(30)
        layout.addWidget(self.status_label)

        # Steps area — shows completed steps
        self.steps_label = QLabel("")
        self.steps_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.steps_label.setWordWrap(True)
        self.steps_label.setFont(QFont("", 9))
        self.steps_label.setStyleSheet(f"color: {SPLASH_DIM}; background: transparent; padding: 0 32px 20px 32px;")
        self.steps_label.setFixedHeight(80)
        layout.addWidget(self.steps_label)

        self._steps_done = []

        # Opacity effect for the whole window (used for fade-out)
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

    def _center_on_screen(self):
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - self.width()) // 2 + geo.x()
            y = (geo.height() - self.height()) // 2 + geo.y()
            self.move(x, y)

    def set_status(self, text):
        """Update the current loading step."""
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {SPLASH_TEXT}; background: transparent; padding: 8px;")
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    def step_done(self, text):
        """Mark a step as complete and show it in the history."""
        self._steps_done.append(f"  {text}")
        self.steps_label.setText("\n".join(self._steps_done[-4:]))
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    def fade_out(self, on_finished, duration=400):
        """Fade the splash out, then call on_finished."""
        self._anim = QPropertyAnimation(self._opacity, b"opacity")
        self._anim.setDuration(duration)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self._anim.finished.connect(on_finished)
        self._anim.finished.connect(self.close)
        self._anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(SPLASH_BG))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 16, 16)
        painter.end()
