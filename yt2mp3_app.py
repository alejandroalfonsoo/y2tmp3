#!/usr/bin/env python3
"""
yt2mp3 · YouTube → MP3 Converter for macOS
==========================================
Aplicación nativa con GUI estética macOS (PyQt6).

Arquitectura:
  - DownloadWorker(QThread): hilo por descarga con señales Qt para progreso/log.
  - DownloadItem(QWidget): tarjeta de cola con barra y estado por item.
  - MainWindow: ventana frameless con título custom, drag region, drop zone.
  - yt-dlp + ffmpeg: backend de extracción y transcodificación.

Diseño:
  - Frameless window + sombras (NSWindow-like)
  - Vibrancy simulado con gradientes y backdrop semi-transparente
  - Traffic lights funcionales (cerrar / minimizar / maximizar)
  - SF-like tipografía, paleta de macOS (system colors)
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yt_dlp
from PyQt6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, QThread,
    QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath,
    QPalette, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget,
)

# ════════════════════════════════════════════════════════════════════
#  CONSTANTES Y CONFIG
# ════════════════════════════════════════════════════════════════════

APP_NAME = "yt2mp3"
APP_VERSION = "1.0"
DEFAULT_OUTPUT = Path.home() / "Downloads" / "yt2mp3"
DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)

QUALITIES = [("128 kbps", "128"), ("192 kbps", "192"),
             ("256 kbps", "256"), ("320 kbps", "320")]

# Paleta macOS Dark
COLORS = {
    "bg":          "#1c1c1e",
    "bg_chrome":   "#2c2c2e",
    "bg_elev":     "rgba(58, 58, 60, 0.85)",
    "bg_ctrl":     "rgba(118, 118, 128, 0.24)",
    "bg_ctrl_h":   "rgba(118, 118, 128, 0.36)",
    "stroke":      "rgba(255, 255, 255, 0.08)",
    "stroke_s":    "rgba(255, 255, 255, 0.14)",
    "text":        "#f5f5f7",
    "text_2":      "rgba(235, 235, 245, 0.6)",
    "text_3":      "rgba(235, 235, 245, 0.35)",
    "accent":      "#0a84ff",
    "accent_h":    "#2a93ff",
    "green":       "#30d158",
    "red":         "#ff453a",
    "orange":      "#ff9f0a",
    "purple":      "#bf5af2",
    "pink":        "#ff375f",
}

URL_RE = re.compile(
    r"(https?://)?(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)/\S+"
)


# ════════════════════════════════════════════════════════════════════
#  MODELOS
# ════════════════════════════════════════════════════════════════════

@dataclass
class DownloadJob:
    url: str
    quality: str = "192"
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT)
    title: str = ""
    duration: int = 0
    final_path: Optional[Path] = None


# ════════════════════════════════════════════════════════════════════
#  WORKER · descarga en hilo independiente
# ════════════════════════════════════════════════════════════════════

class DownloadWorker(QThread):
    """Hilo que ejecuta yt-dlp y emite señales Qt para la UI."""

    metadata_ready = pyqtSignal(str, int)         # title, duration_s
    progress_changed = pyqtSignal(float, str)     # pct, eta_str
    log = pyqtSignal(str, str)                    # level, msg
    finished_ok = pyqtSignal(str)                 # final_path
    failed = pyqtSignal(str)                      # error_msg

    def __init__(self, job: DownloadJob, parent=None):
        super().__init__(parent)
        self.job = job
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    # ── yt-dlp callbacks ───────────────────────────────────────────
    def _hook(self, d):
        if self._cancelled:
            raise yt_dlp.utils.DownloadError("Cancelado por el usuario")

        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            pct = (done / total * 100) if total else 0
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0
            speed_kb = speed / 1024 if speed else 0
            eta_str = (
                f"{speed_kb:6.0f} KB/s · ETA {eta}s" if speed else "—"
            )
            # 0–85% para descarga, 85–100% para postproceso
            self.progress_changed.emit(pct * 0.85, eta_str)
        elif status == "finished":
            self.progress_changed.emit(85.0, "Convirtiendo a MP3…")
            self.log.emit("info", "Descarga completa, transcodificando…")

    def _postprocessor_hook(self, d):
        if d.get("status") == "started":
            self.log.emit("info", f"Postproceso: {d.get('postprocessor', '')}")
        elif d.get("status") == "finished":
            self.progress_changed.emit(100.0, "Completado")

    # ── Ejecución ──────────────────────────────────────────────────
    def run(self):
        try:
            self.log.emit("info", f"URL: {self.job.url}")
            self.log.emit("info", f"Calidad: {self.job.quality} kbps")
            self.log.emit("info", f"Salida: {self.job.output_dir}")

            outtmpl = str(self.job.output_dir / "%(title)s.%(ext)s")
            opts = {
                "format": "bestaudio/best",
                "outtmpl": outtmpl,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [self._hook],
                "postprocessor_hooks": [self._postprocessor_hook],
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": self.job.quality,
                    },
                    {
                        "key": "FFmpegMetadata",
                    },
                    {
                        "key": "EmbedThumbnail",
                    },
                ],
                "writethumbnail": True,
            }

            with yt_dlp.YoutubeDL(opts) as ydl:
                # Primero solo metadatos para mostrar título antes de bajar
                self.log.emit("info", "Obteniendo metadatos…")
                info = ydl.extract_info(self.job.url, download=False)
                title = info.get("title", "Sin título")
                duration = info.get("duration", 0) or 0
                self.job.title = title
                self.job.duration = duration
                self.metadata_ready.emit(title, duration)
                self.log.emit("ok", f"'{title}' · {self._fmt_dur(duration)}")

                # Descarga
                ydl.download([self.job.url])

            # Localizar el .mp3 final
            final = self.job.output_dir / f"{self._sanitize(title)}.mp3"
            if not final.exists():
                # yt-dlp puede haber sanitizado distinto: buscar el más reciente
                candidates = sorted(
                    self.job.output_dir.glob("*.mp3"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if candidates:
                    final = candidates[0]

            self.job.final_path = final
            self.log.emit("ok", f"Guardado en {final}")
            self.finished_ok.emit(str(final))

        except yt_dlp.utils.DownloadError as e:
            self.log.emit("err", f"yt-dlp: {e}")
            self.failed.emit(str(e))
        except Exception as e:
            self.log.emit("err", f"Excepción: {type(e).__name__}: {e}")
            self.failed.emit(str(e))

    @staticmethod
    def _fmt_dur(s: int) -> str:
        if not s:
            return "—"
        m, sec = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

    @staticmethod
    def _sanitize(name: str) -> str:
        # Aproximación a la sanitización de yt-dlp
        return re.sub(r'[<>:"/\\|?*]', "", name).strip()


# ════════════════════════════════════════════════════════════════════
#  WIDGETS · controles personalizados
# ════════════════════════════════════════════════════════════════════

class TrafficLight(QPushButton):
    """Botón circular tipo macOS (cerrar/minimizar/maximizar)."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background: {color};
                border-radius: 6px;
                border: 0.5px solid rgba(0, 0, 0, 0.25);
            }}
            QPushButton:hover {{
                background: {color};
                border: 0.5px solid rgba(0, 0, 0, 0.45);
            }}
        """)


class TitleBar(QWidget):
    """Barra de título personalizada con traffic lights."""

    close_clicked = pyqtSignal()
    minimize_clicked = pyqtSignal()
    maximize_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)
        self.setObjectName("titlebar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        self.btn_close = TrafficLight("#ff5f57")
        self.btn_min = TrafficLight("#febc2e")
        self.btn_max = TrafficLight("#28c840")
        self.btn_close.clicked.connect(self.close_clicked.emit)
        self.btn_min.clicked.connect(self.minimize_clicked.emit)
        self.btn_max.clicked.connect(self.maximize_clicked.emit)

        layout.addWidget(self.btn_close)
        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)
        layout.addStretch()

        self.title = QLabel(f"{APP_NAME}")
        self.title.setStyleSheet(f"""
            color: {COLORS['text_2']};
            font-size: 13px;
            font-weight: 500;
            letter-spacing: 0.2px;
        """)
        layout.addWidget(self.title)
        layout.addStretch()
        layout.addItem(QSpacerItem(56, 1))  # compensar traffic lights

        self._drag_pos: Optional[QPoint] = None

    # Permitir arrastrar la ventana desde la barra
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                e.globalPosition().toPoint()
                - self.window().frameGeometry().topLeft()
            )
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None


class Card(QFrame):
    """Tarjeta con vidrio esmerilado simulado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)


class DownloadItem(QFrame):
    """Tarjeta visual de un job en la cola."""

    def __init__(self, job: DownloadJob, parent=None):
        super().__init__(parent)
        self.job = job
        self.worker: Optional[DownloadWorker] = None
        self.setObjectName("downloadItem")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Fila superior: título + estado
        top = QHBoxLayout()
        self.title_lbl = QLabel("Resolviendo metadatos…")
        self.title_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 13px; font-weight: 500;"
        )
        self.title_lbl.setWordWrap(False)
        self.title_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        self.status_lbl = QLabel("En cola")
        self.status_lbl.setStyleSheet(
            f"color: {COLORS['text_2']}; font-size: 11px; font-weight: 500;"
        )

        top.addWidget(self.title_lbl)
        top.addWidget(self.status_lbl)
        layout.addLayout(top)

        # Subtítulo: URL truncada
        self.url_lbl = QLabel(self._truncate(job.url, 70))
        self.url_lbl.setStyleSheet(
            f"color: {COLORS['text_3']}; font-size: 11px;"
        )
        layout.addWidget(self.url_lbl)

        # Progress bar
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        layout.addWidget(self.bar)

        # Meta
        self.meta_lbl = QLabel(f"{job.quality} kbps · esperando")
        self.meta_lbl.setStyleSheet(
            f"color: {COLORS['text_3']}; font-size: 10px; font-variant: tabular-nums;"
        )
        layout.addWidget(self.meta_lbl)

    @staticmethod
    def _truncate(s: str, n: int) -> str:
        return s if len(s) <= n else s[: n - 1] + "…"

    # ── Conexión con worker ────────────────────────────────────────
    def attach_worker(self, worker: DownloadWorker):
        self.worker = worker
        worker.metadata_ready.connect(self._on_metadata)
        worker.progress_changed.connect(self._on_progress)
        worker.finished_ok.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        self.status_lbl.setText("Descargando")
        self.status_lbl.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: 11px; font-weight: 500;"
        )

    def _on_metadata(self, title: str, duration: int):
        self.title_lbl.setText(self._truncate(title, 60))

    def _on_progress(self, pct: float, eta: str):
        self.bar.setValue(int(pct * 10))
        self.meta_lbl.setText(f"{self.job.quality} kbps · {pct:.1f}% · {eta}")

    def _on_done(self, path: str):
        self.status_lbl.setText("Listo")
        self.status_lbl.setStyleSheet(
            f"color: {COLORS['green']}; font-size: 11px; font-weight: 600;"
        )
        self.bar.setValue(1000)
        self.meta_lbl.setText(f"✓ {Path(path).name}")

    def _on_failed(self, err: str):
        self.status_lbl.setText("Error")
        self.status_lbl.setStyleSheet(
            f"color: {COLORS['red']}; font-size: 11px; font-weight: 600;"
        )
        self.meta_lbl.setText(self._truncate(err, 80))


# ════════════════════════════════════════════════════════════════════
#  VENTANA PRINCIPAL
# ════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(820, 720)
        self.setMinimumSize(680, 580)

        self.workers: list[DownloadWorker] = []
        self.items: list[DownloadItem] = []
        self.output_dir = DEFAULT_OUTPUT
        self.current_quality = "192"

        self._build_ui()
        self._apply_styles()

    # ── Construcción de UI ─────────────────────────────────────────
    def _build_ui(self):
        # Contenedor con esquinas redondeadas
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Title bar
        self.titlebar = TitleBar()
        self.titlebar.close_clicked.connect(self.close)
        self.titlebar.minimize_clicked.connect(self.showMinimized)
        self.titlebar.maximize_clicked.connect(self._toggle_maximize)
        v.addWidget(self.titlebar)

        # Body con padding
        body = QWidget()
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(28, 16, 28, 24)
        body_l.setSpacing(16)
        v.addWidget(body, 1)

        # Hero
        hero = QWidget()
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(0, 0, 0, 0)
        hero_l.setSpacing(4)

        title = QLabel("YouTube → MP3")
        title.setObjectName("heroTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("Descarga audio de alta calidad con metadatos y carátula")
        subtitle.setObjectName("heroSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        hero_l.addWidget(title)
        hero_l.addWidget(subtitle)
        body_l.addWidget(hero)

        # Card 1: input
        input_card = Card()
        input_l = QVBoxLayout(input_card)
        input_l.setContentsMargins(20, 18, 20, 18)
        input_l.setSpacing(12)

        lbl_section = QLabel("URL DEL VÍDEO")
        lbl_section.setObjectName("sectionLabel")
        input_l.addWidget(lbl_section)

        url_row = QHBoxLayout()
        url_row.setSpacing(10)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.url_input.setObjectName("urlInput")
        self.url_input.setMinimumHeight(40)
        self.url_input.returnPressed.connect(self._on_add)

        self.btn_paste = QPushButton("Pegar")
        self.btn_paste.setObjectName("btnSecondary")
        self.btn_paste.setFixedHeight(40)
        self.btn_paste.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_paste.clicked.connect(self._paste_clipboard)

        self.btn_add = QPushButton("Añadir a la cola")
        self.btn_add.setObjectName("btnPrimary")
        self.btn_add.setFixedHeight(40)
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(self._on_add)

        url_row.addWidget(self.url_input, 1)
        url_row.addWidget(self.btn_paste)
        url_row.addWidget(self.btn_add)
        input_l.addLayout(url_row)

        # Opciones (calidad + carpeta)
        opts_row = QHBoxLayout()
        opts_row.setSpacing(8)

        opts_row.addWidget(self._make_label("Calidad"))
        for label, value in QUALITIES:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setObjectName("qualityBtn")
            btn.setProperty("quality", value)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if value == self.current_quality:
                btn.setChecked(True)
            btn.clicked.connect(lambda _, b=btn: self._on_quality(b))
            opts_row.addWidget(btn)

        opts_row.addStretch()

        self.folder_btn = QPushButton(self._folder_label())
        self.folder_btn.setObjectName("btnSecondary")
        self.folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_btn.clicked.connect(self._choose_folder)
        opts_row.addWidget(self.folder_btn)

        input_l.addLayout(opts_row)
        body_l.addWidget(input_card)

        # Card 2: cola
        queue_card = Card()
        queue_l = QVBoxLayout(queue_card)
        queue_l.setContentsMargins(20, 18, 20, 18)
        queue_l.setSpacing(10)

        head_row = QHBoxLayout()
        lbl_q = QLabel("COLA DE DESCARGAS")
        lbl_q.setObjectName("sectionLabel")
        self.queue_count = QLabel("0")
        self.queue_count.setObjectName("queueCount")
        head_row.addWidget(lbl_q)
        head_row.addStretch()
        head_row.addWidget(self.queue_count)
        queue_l.addLayout(head_row)

        # Scroll para items
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.queue_container = QWidget()
        self.queue_layout = QVBoxLayout(self.queue_container)
        self.queue_layout.setContentsMargins(0, 0, 0, 0)
        self.queue_layout.setSpacing(8)
        self.queue_layout.addStretch()

        self.scroll.setWidget(self.queue_container)
        queue_l.addWidget(self.scroll, 1)

        # Empty state
        self.empty_label = QLabel(
            "Pega o arrastra una URL de YouTube para empezar"
        )
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        queue_l.addWidget(self.empty_label, 1)

        body_l.addWidget(queue_card, 1)

        # Card 3: log técnico
        log_card = Card()
        log_l = QVBoxLayout(log_card)
        log_l.setContentsMargins(20, 14, 20, 14)
        log_l.setSpacing(8)

        lbl_log = QLabel("LOG TÉCNICO")
        lbl_log.setObjectName("sectionLabel")
        log_l.addWidget(lbl_log)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("logView")
        self.log_view.setFixedHeight(120)
        log_l.addWidget(self.log_view)

        body_l.addWidget(log_card)

        # Footer
        footer = QLabel(
            f"yt-dlp · ffmpeg · PyQt6 · v{APP_VERSION}"
        )
        footer.setObjectName("footer")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_l.addWidget(footer)

        # Drag & drop a nivel de ventana
        self.setAcceptDrops(True)

        self._log("info", f"Salida: {self.output_dir}")
        self._log("info", "Listo. Pega una URL para empezar.")

    def _make_label(self, text):
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {COLORS['text_2']}; font-size: 12px; font-weight: 500;"
        )
        return l

    def _folder_label(self) -> str:
        # Mostrar ruta abreviada
        try:
            rel = self.output_dir.relative_to(Path.home())
            return f"~/{rel}"
        except ValueError:
            return str(self.output_dir)

    # ── Estilos ────────────────────────────────────────────────────
    def _apply_styles(self):
        self.setStyleSheet(f"""
            QWidget#root {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {COLORS['bg']},
                    stop:1 #131315
                );
                border: 1px solid {COLORS['stroke']};
                border-radius: 16px;
            }}
            QWidget#titlebar {{
                background: rgba(0, 0, 0, 0.18);
                border-top-left-radius: 16px;
                border-top-right-radius: 16px;
                border-bottom: 1px solid {COLORS['stroke']};
            }}
            QLabel#heroTitle {{
                color: {COLORS['text']};
                font-size: 26px;
                font-weight: 600;
                letter-spacing: -0.5px;
                margin-top: 8px;
            }}
            QLabel#heroSubtitle {{
                color: {COLORS['text_2']};
                font-size: 13px;
                margin-bottom: 6px;
            }}
            QFrame#card {{
                background: {COLORS['bg_chrome']};
                border: 1px solid {COLORS['stroke']};
                border-radius: 14px;
            }}
            QLabel#sectionLabel {{
                color: {COLORS['text_3']};
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1.4px;
            }}
            QLabel#emptyState {{
                color: {COLORS['text_3']};
                font-size: 13px;
                padding: 30px;
            }}
            QLabel#queueCount {{
                color: {COLORS['text_2']};
                font-size: 11px;
                font-weight: 600;
                background: {COLORS['bg_ctrl']};
                padding: 2px 10px;
                border-radius: 9px;
            }}
            QLabel#footer {{
                color: {COLORS['text_3']};
                font-size: 10px;
                letter-spacing: 0.4px;
                margin-top: 4px;
            }}
            QLineEdit#urlInput {{
                background: {COLORS['bg_ctrl']};
                border: 0.5px solid {COLORS['stroke_s']};
                border-radius: 9px;
                color: {COLORS['text']};
                font-size: 13px;
                padding: 0 14px;
                selection-background-color: {COLORS['accent']};
            }}
            QLineEdit#urlInput:focus {{
                border: 1px solid {COLORS['accent']};
                background: rgba(118, 118, 128, 0.32);
            }}
            QPushButton#btnPrimary {{
                background: {COLORS['accent']};
                color: white;
                font-size: 13px;
                font-weight: 600;
                border: none;
                border-radius: 9px;
                padding: 0 18px;
            }}
            QPushButton#btnPrimary:hover {{ background: {COLORS['accent_h']}; }}
            QPushButton#btnPrimary:pressed {{ background: #0070e0; }}
            QPushButton#btnPrimary:disabled {{
                background: rgba(10, 132, 255, 0.35);
                color: rgba(255, 255, 255, 0.5);
            }}
            QPushButton#btnSecondary {{
                background: {COLORS['bg_ctrl']};
                color: {COLORS['text']};
                font-size: 12px;
                font-weight: 500;
                border: 0.5px solid {COLORS['stroke_s']};
                border-radius: 8px;
                padding: 8px 14px;
            }}
            QPushButton#btnSecondary:hover {{ background: {COLORS['bg_ctrl_h']}; }}
            QPushButton#qualityBtn {{
                background: {COLORS['bg_ctrl']};
                color: {COLORS['text_2']};
                font-size: 11px;
                font-weight: 500;
                border: 0.5px solid {COLORS['stroke']};
                border-radius: 7px;
                padding: 6px 12px;
            }}
            QPushButton#qualityBtn:hover {{ background: {COLORS['bg_ctrl_h']}; }}
            QPushButton#qualityBtn:checked {{
                background: rgba(10, 132, 255, 0.22);
                color: {COLORS['accent_h']};
                border: 0.5px solid {COLORS['accent']};
            }}
            QFrame#downloadItem {{
                background: rgba(255, 255, 255, 0.03);
                border: 0.5px solid {COLORS['stroke']};
                border-radius: 10px;
            }}
            QProgressBar {{
                background: {COLORS['bg_ctrl']};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {COLORS['accent']},
                    stop:1 {COLORS['purple']}
                );
                border-radius: 3px;
            }}
            QPlainTextEdit#logView {{
                background: rgba(0, 0, 0, 0.35);
                border: 0.5px solid {COLORS['stroke']};
                border-radius: 8px;
                color: {COLORS['text_2']};
                font-family: "SF Mono", "Menlo", "Monaco", monospace;
                font-size: 11px;
                padding: 8px;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255, 255, 255, 0.18);
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(255, 255, 255, 0.3);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

    # ── Eventos ventana ────────────────────────────────────────────
    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def dragEnterEvent(self, e):
        if e.mimeData().hasText() or e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        text = ""
        if e.mimeData().hasText():
            text = e.mimeData().text()
        elif e.mimeData().hasUrls():
            text = e.mimeData().urls()[0].toString()
        for line in text.splitlines():
            line = line.strip()
            if URL_RE.search(line):
                self.url_input.setText(line)
                self._on_add()

    # ── Acciones ───────────────────────────────────────────────────
    def _paste_clipboard(self):
        cb = QApplication.clipboard().text().strip()
        if cb:
            self.url_input.setText(cb)
        if URL_RE.search(cb):
            self._on_add()

    def _on_quality(self, btn):
        self.current_quality = btn.property("quality")
        for child in btn.parent().findChildren(QPushButton):
            if child.objectName() == "qualityBtn":
                child.setChecked(child is btn)
        self._log("info", f"Calidad fijada a {self.current_quality} kbps")

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, "Carpeta de salida", str(self.output_dir)
        )
        if d:
            self.output_dir = Path(d)
            self.folder_btn.setText(self._folder_label())
            self._log("info", f"Salida: {self.output_dir}")

    def _on_add(self):
        url = self.url_input.text().strip()
        if not url:
            return
        if not URL_RE.search(url):
            self._log("err", "URL no válida (debe ser youtube.com o youtu.be)")
            return

        job = DownloadJob(
            url=url, quality=self.current_quality, output_dir=self.output_dir
        )
        item = DownloadItem(job)
        worker = DownloadWorker(job)
        item.attach_worker(worker)
        worker.log.connect(self._log)
        worker.finished_ok.connect(lambda *_: self._on_worker_done())
        worker.failed.connect(lambda *_: self._on_worker_done())

        # Insertar antes del stretch
        self.queue_layout.insertWidget(self.queue_layout.count() - 1, item)
        self.items.append(item)
        self.workers.append(worker)
        self._update_queue_count()
        self.empty_label.setVisible(False)

        worker.start()
        self.url_input.clear()

    def _on_worker_done(self):
        # Limpieza opcional: nada que hacer ahora, los items quedan visibles
        pass

    def _update_queue_count(self):
        n = len(self.items)
        self.queue_count.setText(str(n))
        self.empty_label.setVisible(n == 0)

    # ── Log ────────────────────────────────────────────────────────
    def _log(self, level: str, msg: str):
        color = {
            "info": COLORS["text_2"],
            "ok":   COLORS["green"],
            "warn": COLORS["orange"],
            "err":  COLORS["red"],
        }.get(level, COLORS["text_2"])
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendHtml(
            f'<span style="color:{COLORS["text_3"]};">[{ts}]</span> '
            f'<span style="color:{color};">{msg}</span>'
        )

    # ── Cierre limpio ──────────────────────────────────────────────
    def closeEvent(self, e):
        for w in self.workers:
            if w.isRunning():
                w.cancel()
                w.wait(2000)
        e.accept()


# ════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")  # base neutral, lo demás lo hacemos por QSS

    # Fuente del sistema (SF Pro en macOS automáticamente)
    font = QFont(".AppleSystemUIFont", 13)
    app.setFont(font)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()