from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional, Tuple

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)


@dataclass
class TransformState:
    zoom: float = 1.0
    angle_deg: int = 0
    offset_x: float = 0.0
    offset_y: float = 0.0


class ImageCanvas(QWidget):
    def __init__(self, editor: "ImageEditor", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.editor = editor
        self.setMinimumSize(960, 640)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f0f0f0"))
        if not self.editor._preview_pixmap:
            return

        painter.drawPixmap(self.editor._crop_rect[0], self.editor._crop_rect[1], self.editor._preview_pixmap)

        cw = self.width()
        ch = self.height()
        x0, y0, x1, y1 = self.editor._crop_rect
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, 0, cw, int(y0))
        painter.drawRect(0, int(y1), cw, ch - int(y1))
        painter.drawRect(0, int(y0), int(x0), int(y1 - y0))
        painter.drawRect(int(x1), int(y0), cw - int(x1), int(y1 - y0))

        painter.setPen(QPen(QColor("#000000"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))

    def mousePressEvent(self, event):
        return self.editor._on_drag_start(event)

    def mouseMoveEvent(self, event):
        return self.editor._on_drag_move(event)

    def mouseReleaseEvent(self, event):
        return self.editor._on_drag_end(event)

    def wheelEvent(self, event):
        return self.editor._on_mousewheel(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.editor._schedule_render()


class ImageEditor(QDialog):
    def __init__(
        self,
        pil_image: Image.Image,
        output_size: Tuple[int, int],
        title: str = "Upravit obrázek",
    ):
        super().__init__()
        self.setWindowTitle(title)
        self.setModal(True)

        self.original = pil_image.convert("RGBA")
        self.out_w, self.out_h = output_size
        self.state = TransformState()

        ow, oh = self.original.size
        self.base_scale = max(self.out_w / max(1, ow), self.out_h / max(1, oh))

        self._pending_render = False
        self._preview_pixmap: Optional[QPixmap] = None
        self._crop_rect = (0, 0, 1, 1)
        self._drag_start: Optional[Tuple[float, float, float, float]] = None

        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(30, 500)
        self.zoom_slider.setValue(int(self.state.zoom * 100))
        self.zoom_slider.valueChanged.connect(self._on_slider_change)

        self.zoom_label = QLabel(f"{self.state.zoom:.2f}×")
        self.zoom_label.setAlignment(Qt.AlignCenter)

        self.canvas = ImageCanvas(self)

        controls_layout = QHBoxLayout()
        self._add_control_button("Otočit vlevo 90°", lambda: self._rotate(-90), controls_layout)
        self._add_control_button("Otočit vpravo 90°", lambda: self._rotate(90), controls_layout)
        self._add_control_button("↺ -5°", lambda: self._rotate(-5), controls_layout)
        self._add_control_button("↻ +5°", lambda: self._rotate(5), controls_layout)
        self._add_control_button("Reset", self._reset, controls_layout)

        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("Lupa:"))
        zoom_layout.addWidget(self.zoom_slider)
        zoom_layout.addWidget(self.zoom_label)

        action_layout = QHBoxLayout()
        save_btn = QPushButton("Uložit")
        cancel_btn = QPushButton("Zrušit")
        save_btn.clicked.connect(self._on_save)
        cancel_btn.clicked.connect(self._on_cancel)
        action_layout.addStretch(1)
        action_layout.addWidget(save_btn)
        action_layout.addWidget(cancel_btn)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.canvas)
        main_layout.addLayout(controls_layout)
        main_layout.addLayout(zoom_layout)
        main_layout.addLayout(action_layout)
        self.setLayout(main_layout)

        self._result_png: Optional[bytes] = None
        self._schedule_render()

    def _add_control_button(self, text: str, handler, layout: QHBoxLayout) -> None:
        btn = QPushButton(text)
        btn.clicked.connect(handler)
        layout.addWidget(btn)

    def _schedule_render(self) -> None:
        if self._pending_render:
            return
        self._pending_render = True
        QTimer.singleShot(30, self._render)

    def _render(self) -> None:
        self._pending_render = False
        cw = max(1, self.canvas.width())
        ch = max(1, self.canvas.height())
        target_aspect = self.out_w / self.out_h
        pad = 20
        avail_w = max(1, cw - pad * 2)
        avail_h = max(1, ch - pad * 2)
        if avail_w / avail_h > target_aspect:
            crop_h = avail_h
            crop_w = int(round(crop_h * target_aspect))
        else:
            crop_w = avail_w
            crop_h = int(round(crop_w / target_aspect))

        x0 = (cw - crop_w) / 2
        y0 = (ch - crop_h) / 2
        self._crop_rect = (x0, y0, x0 + crop_w, y0 + crop_h)

        out_img = self._render_output_image()
        preview = out_img.resize((crop_w, crop_h), resample=Image.LANCZOS)
        qimage = ImageQt(preview)
        self._preview_pixmap = QPixmap.fromImage(qimage)
        self.canvas.update()

    def _render_output_image(self) -> Image.Image:
        base = Image.new("RGBA", (self.out_w, self.out_h), (255, 255, 255, 255))
        ow, oh = self.original.size
        total_scale = self.base_scale * self.state.zoom
        sw = max(1, int(round(ow * total_scale)))
        sh = max(1, int(round(oh * total_scale)))
        try:
            scaled = self.original.resize((sw, sh), resample=Image.LANCZOS)
        except Exception:
            scaled = self.original

        angle = self.state.angle_deg % 360
        if angle != 0:
            rotated = scaled.rotate(angle, expand=True, resample=Image.BICUBIC)
        else:
            rotated = scaled

        rw, rh = rotated.size
        cx = self.out_w / 2 + self.state.offset_x
        cy = self.out_h / 2 + self.state.offset_y

        left = int(round(cx - rw / 2))
        top = int(round(cy - rh / 2))

        tmp = Image.new("RGBA", (self.out_w, self.out_h), (0, 0, 0, 0))
        tmp.paste(rotated, (left, top), rotated)
        return Image.alpha_composite(base, tmp)

    def _on_slider_change(self, value: int) -> None:
        zoom_value = max(30, min(500, value)) / 100.0
        self.state.zoom = zoom_value
        self._update_zoom_label()
        self._schedule_render()

    def _update_zoom_label(self) -> None:
        self.zoom_label.setText(f"{self.state.zoom:.2f}×")

    def _zoom(self, factor: float) -> None:
        self.state.zoom = float(max(0.3, min(8.0, self.state.zoom * factor)))
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(self.state.zoom * 100))
        self.zoom_slider.blockSignals(False)
        self._update_zoom_label()
        self._schedule_render()

    def _rotate(self, deg: int) -> None:
        self.state.angle_deg = int((self.state.angle_deg + deg) % 360)
        self._schedule_render()

    def _reset(self) -> None:
        self.state = TransformState()
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(self.state.zoom * 100))
        self.zoom_slider.blockSignals(False)
        self._update_zoom_label()
        self._schedule_render()

    def _on_drag_start(self, event) -> None:
        pos = event.position()
        self._drag_start = (pos.x(), pos.y(), self.state.offset_x, self.state.offset_y)

    def _on_drag_move(self, event) -> None:
        if not self._drag_start:
            return
        pos = event.position()
        dx = pos.x() - self._drag_start[0]
        dy = pos.y() - self._drag_start[1]

        crop_x0, crop_y0, crop_x1, crop_y1 = self._crop_rect
        crop_w = max(1, crop_x1 - crop_x0)
        crop_h = max(1, crop_y1 - crop_y0)
        scale_x = self.out_w / crop_w
        scale_y = self.out_h / crop_h

        self.state.offset_x = self._drag_start[2] + dx * scale_x
        self.state.offset_y = self._drag_start[3] + dy * scale_y
        self._schedule_render()

    def _on_drag_end(self, event) -> None:
        self._drag_start = None

    def _on_mousewheel(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        steps = delta / 120.0
        factor = 1.1 ** steps
        self._zoom(factor)

    def _on_save(self) -> None:
        try:
            out = self._render_output_image().convert("RGB")
            bio = io.BytesIO()
            out.save(bio, format="PNG")
            self._result_png = bio.getvalue()
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se uložit obrázek: {exc}")

    def _on_cancel(self) -> None:
        self._result_png = None
        self.reject()

    def get_result(self) -> Optional[bytes]:
        return self._result_png


def edit_image_dialog(parent: QWidget, pil_image: Image.Image, output_size: Tuple[int, int]) -> Optional[bytes]:
    dlg = ImageEditor(pil_image, output_size)
    if dlg.exec():
        return dlg.get_result()
    return None
