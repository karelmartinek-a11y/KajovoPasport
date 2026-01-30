from __future__ import annotations

import sys
import traceback
from typing import Dict, List, Optional, Tuple

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QSize, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .db import Database, Card, copy_db_file
from .image_editor import edit_image_dialog
from .pdf_utils import generate_card_pdf, make_temp_pdf_path, open_pdf, print_pdf_windows
from .settings import Settings, load_settings, save_settings, default_db_path

APP_TITLE = "KajovoPasport"
APP_MARGIN = 16
APP_BG = QColor("#f4f6fb")
PREVIEW_BG = QColor("#ffffff")
CELL_BORDER = QColor("#d1dae8")
CELL_BG = QColor("#fbfbff")
LABEL_COLOR = QColor("#1f2a37")
TITLE_FONT = QFont("Segoe UI Variable", 18, QFont.Bold)
SUBTITLE_FONT = QFont("Segoe UI Variable", 10)
FIELD_FONT = QFont("Segoe UI Variable", 9)
CELL_LABEL_FONT = QFont("Segoe UI Variable", 9, QFont.Bold)
GRID_ROWS = 4
GRID_COLS = 4
FIELDS: List[Tuple[str, str]] = [
    ("skrin", "SKŘÍŇ"),
    ("satna", "ŠATNA"),
    ("stolek", "STŮL"),
    ("okno_obyvak", "OKNO LOŽNICE"),
    ("tv", "TV"),
    ("svetla_obyvak", "SVĚTLA"),
    ("postel_1", "POSTEL 1"),
    ("postel_2", "POSTEL 2"),
    ("postel_3", "POSTEL 3"),
    ("okno_koupelna", "OKNO WC"),
    ("wc", "WC"),
    ("umyvadlo", "UMYVADLO"),
    ("sprcha", "SPRCHA"),
    ("koupelna_svetla", "OSVĚTLENÍ KOUPELNY"),
    ("dvere_vchod", "DVEŘE 1"),
    ("dvere_koupelna", "DVEŘE 2"),
]



class PreviewWidget(QWidget):
    fieldClicked = Signal(str)
    fieldRightClicked = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.card_name: str = ""
        self.field_images: Dict[str, bytes] = {}
        self.cell_boxes: List[Tuple[str, QRectF]] = []
        self.image_bounds: Dict[str, QRectF] = {}

    def sizeHint(self) -> QSize:
        return QSize(960, 720)

    def set_card(self, name: str, images: Dict[str, bytes]) -> None:
        self.card_name = name
        self.field_images = images
        self.update()

    def clear_card(self) -> None:
        self.card_name = ""
        self.field_images = {}
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), APP_BG)
        cw = max(1, self.width())
        ch = max(1, self.height())
        pad = APP_MARGIN
        a4_ratio = 210 / 297
        avail_w = max(1, cw - 2 * pad)
        avail_h = max(1, ch - 2 * pad)
        page_h = avail_h
        page_w = int(page_h * a4_ratio)
        if page_w > avail_w:
            page_w = avail_w
            page_h = int(page_w / a4_ratio)

        px0 = (cw - page_w) / 2
        py0 = (ch - page_h) / 2
        grid_margin = max(12, int(page_w * 0.03))
        ix0 = px0 + grid_margin
        iy0 = py0 + grid_margin
        ix1 = px0 + page_w - grid_margin
        iy1 = py0 + page_h - grid_margin

        # Draw page frame
        painter.setPen(QPen(CELL_BORDER, 2))
        painter.setBrush(PREVIEW_BG)
        painter.drawRect(px0, py0, page_w, page_h)

        # Header area
        painter.setFont(TITLE_FONT)
        painter.setPen(LABEL_COLOR)
        header_height = 30
        title_rect = QRectF(ix0, iy0, ix1 - ix0, header_height)
        title_text = (self.card_name or "").upper()
        painter.drawText(title_rect, Qt.AlignCenter | Qt.AlignVCenter, title_text)
        grid_top = iy0 + header_height + 4
        grid_bottom = iy1
        grid_h = max(1, grid_bottom - grid_top)
        grid_w = max(1, ix1 - ix0)

        gap = 1
        cell_w = (grid_w - gap * (GRID_COLS - 1)) / GRID_COLS
        cell_h = (grid_h - gap * (GRID_ROWS - 1)) / GRID_ROWS
        label_h = max(10, int(cell_h * 0.08))
        img_pad = 4

        self.cell_boxes.clear()
        self.image_bounds.clear()

        for idx, (key, label) in enumerate(FIELDS):
            row = idx // GRID_COLS
            col = idx % GRID_COLS
            x = ix0 + col * (cell_w + gap)
            y = grid_top + row * (cell_h + gap)
            rect = QRectF(x, y, cell_w, cell_h)

            painter.setPen(QPen(CELL_BORDER, 1))
            painter.setBrush(CELL_BG)
            painter.drawRoundedRect(rect, 4, 4)

            label_rect = QRectF(
                x + img_pad,
                y + cell_h - label_h - img_pad,
                cell_w - 2 * img_pad,
                label_h,
            )
            painter.setPen(LABEL_COLOR)
            painter.setFont(CELL_LABEL_FONT)
            metrics = painter.fontMetrics()
            max_width = max(1, int(label_rect.width()))
            text_to_draw = metrics.elidedText(label.upper(), Qt.ElideRight, max_width)
            painter.drawText(label_rect, Qt.AlignCenter | Qt.AlignVCenter, text_to_draw)

            img_rect = QRectF(
                x + img_pad,
                y + img_pad,
                cell_w - 2 * img_pad,
                cell_h - label_h - 2 * img_pad,
            )
            painter.setPen(QPen(QColor("#d6d9e3"), 1))
            painter.setBrush(Qt.white)
            painter.drawRect(img_rect)

            self.cell_boxes.append((key, rect))
            self.image_bounds[key] = img_rect

            png = self.field_images.get(key)
            if png:
                image = QImage.fromData(png)
                if not image.isNull():
                    pixmap = QPixmap.fromImage(image)
                    scaled = pixmap.scaled(
                        int(img_rect.width()),
                        int(img_rect.height()),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                    dx = img_rect.x() + (img_rect.width() - scaled.width()) / 2
                    dy = img_rect.y() + (img_rect.height() - scaled.height()) / 2
                    painter.drawPixmap(int(dx), int(dy), scaled)

        if not self.card_name:
            painter.setFont(SUBTITLE_FONT)
            painter.setPen(QColor("#6b7280"))
            painter.drawText(
                QRectF(px0, py0, page_w, page_h),
                Qt.AlignCenter,
                "VLEVO VYTVOŘTE NEBO VYBERTE PASPORTNÍ KARTU.",
            )

    def field_at(self, pos):
        for key, rect in self.cell_boxes:
            if rect.contains(pos):
                return key
        return None

    def mousePressEvent(self, event):
        key = self.field_at(event.position())
        if not key:
            return
        if event.button() == Qt.LeftButton:
            self.fieldClicked.emit(key)
        elif event.button() == Qt.RightButton:
            self.fieldRightClicked.emit(key)


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("NastavenÃ­")
        self.setMinimumSize(480, 200)
        self.settings = settings

        layout = QVBoxLayout()
        self.setLayout(layout)

        db_layout = QHBoxLayout()
        db_label = QLabel("DatabÃ¡ze (SQLite soubor):")
        self.db_edit = QLineEdit(settings.db_path)
        db_button = QPushButton("Vybratâ¦")
        db_button.clicked.connect(self._choose_db)
        db_layout.addWidget(db_label)
        db_layout.addWidget(self.db_edit)
        db_layout.addWidget(db_button)
        layout.addLayout(db_layout)

        width_layout = QHBoxLayout()
        width_label = QLabel("Å Ã­Åka exportu (px):")
        self.width_spin = QSpinBox()
        self.width_spin.setRange(400, 3200)
        self.width_spin.setSingleStep(100)
        self.width_spin.setValue(settings.output_width_px)
        width_layout.addWidget(width_label)
        width_layout.addWidget(self.width_spin)
        layout.addLayout(width_layout)

        info_label = QLabel("PomÄr oÅezu se volÃ­ podle layoutu a nenÃ­ tÅeba jej mÄnit.")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        save_btn = QPushButton("UloÅ¾it")
        cancel_btn = QPushButton("ZruÅ¡it")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _choose_db(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Vyberte nebo vytvoÅte databÃ¡zi",
            self.db_edit.text(),
            "SQLite DB (*.db *.sqlite *.sqlite3);;VÅ¡e (*.*)",
        )
        if path:
            self.db_edit.setText(path)

    def get_values(self) -> Settings:
        return Settings(
            db_path=self.db_edit.text().strip() or str(default_db_path()),
            output_width_px=self.width_spin.value(),
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 800)

        self.settings = load_settings()
        self.db = Database(self.settings.db_path)
        self.cards: List[Card] = []
        self.current_card: Optional[Card] = None
        self.current_images: Dict[str, bytes] = {}

        central = QWidget()
        main_layout = QVBoxLayout()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        header = QLabel(APP_TITLE)
        header.setFont(TITLE_FONT)
        main_layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        self.card_list = QListWidget()
        self.card_list.currentTextChanged.connect(self._on_card_select)
        splitter.addWidget(self.card_list)

        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_panel.setLayout(right_layout)
        splitter.addWidget(right_panel)

        self.preview = PreviewWidget()
        self.preview.fieldClicked.connect(self._open_image_for_field)
        self.preview.fieldRightClicked.connect(self._clear_image_for_field)
        right_layout.addWidget(self.preview)

        controls = QHBoxLayout()
        add_btn = QPushButton("PÅidat")
        edit_btn = QPushButton("Upravit")
        delete_btn = QPushButton("Smazat")
        pdf_btn = QPushButton("PDF")
        print_btn = QPushButton("Tisk")
        save_btn = QPushButton("UloÅ¾it")
        settings_btn = QPushButton("NastavenÃ­")

        add_btn.clicked.connect(self._add_card)
        edit_btn.clicked.connect(self._rename_card)
        delete_btn.clicked.connect(self._delete_card)
        pdf_btn.clicked.connect(self._export_pdf)
        print_btn.clicked.connect(self._print_card)
        save_btn.clicked.connect(self._commit)
        settings_btn.clicked.connect(self._open_settings)

        for btn in (add_btn, edit_btn, delete_btn, pdf_btn, print_btn, save_btn, settings_btn):
            controls.addWidget(btn)

        right_layout.addLayout(controls)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.refresh_cards()
        self.select_first_card()

    def refresh_cards(self) -> None:
        self.cards = self.db.list_cards()
        self.card_list.clear()
        for card in self.cards:
            item = QListWidgetItem(card.name)
            self.card_list.addItem(item)

    def select_first_card(self) -> None:
        if not self.cards:
            self.current_card = None
            self.current_images = {}
            self.preview.clear_card()
            return
        self.card_list.setCurrentRow(0)

    def _on_card_select(self, name: str) -> None:
        card = next((c for c in self.cards if c.name == name), None)
        if card:
            self.current_card = card
            self.current_images = self.db.get_images_for_card(card.id)
            self.preview.set_card(card.name, self.current_images)

    def _add_card(self) -> None:
        name, ok = QInputDialog.getText(self, "NovÃ¡ karta", "Zadejte nÃ¡zev pasportnÃ­ karty:")
        if ok and name.strip():
            try:
                self.db.create_card(name.strip())
                self.refresh_cards()
                self.select_card_by_name(name.strip())
            except Exception as exc:
                QMessageBox.critical(self, "Chyba", f"NepodaÅilo se vytvoÅit kartu: {exc}")

    def select_card_by_name(self, name: str):
        matches = self.card_list.findItems(name, Qt.MatchExactly)
        if matches:
            self.card_list.setCurrentItem(matches[0])

    def _rename_card(self) -> None:
        if not self.current_card:
            return
        name, ok = QInputDialog.getText(
            self,
            "Upravit kartu",
            "NovÃ½ nÃ¡zev:",
            text=self.current_card.name,
        )
        if ok and name.strip():
            try:
                self.db.rename_card(self.current_card.id, name.strip())
                self.refresh_cards()
                self.select_card_by_name(name.strip())
            except Exception as exc:
                QMessageBox.critical(self, "Chyba", f"NepodaÅilo se pÅejmenovat kartu: {exc}")

    def _delete_card(self) -> None:
        if not self.current_card:
            return
        resp = QMessageBox.question(
            self,
            "Smazat",
            f"Opravdu smazat kartu '{self.current_card.name}'?",
        )
        if resp == QMessageBox.Yes:
            try:
                self.db.delete_card(self.current_card.id)
                self.refresh_cards()
                self.select_first_card()
            except Exception as exc:
                QMessageBox.critical(self, "Chyba", f"NepodaÅilo se smazat kartu: {exc}")

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == QDialog.Accepted:
            self.settings = dlg.get_values()
            save_settings(self.settings)
            self.db.close()
            self.db = Database(self.settings.db_path)
            self.refresh_cards()
            self.select_first_card()

    def _export_pdf(self) -> None:
        if not self.current_card:
            return
        try:
            pdf_path = make_temp_pdf_path(self.current_card.name)
            generate_card_pdf(pdf_path, self.current_card.name, FIELDS, self.current_images)
            open_pdf(pdf_path)
            self.status_bar.showMessage(f"PDF vytvoÅeno: {pdf_path}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Chyba", f"PDF selhalo: {exc}")

    def _print_card(self) -> None:
        if not self.current_card:
            return
        try:
            pdf_path = make_temp_pdf_path(self.current_card.name)
            generate_card_pdf(pdf_path, self.current_card.name, FIELDS, self.current_images)
            ok = print_pdf_windows(pdf_path)
            if not ok:
                open_pdf(pdf_path)
                QMessageBox.information(
                    self,
                    "Tisk",
                    "NepodaÅilo se spustit tisk automaticky, otevÅel jsem PDF pro manuÃ¡lnÃ­ tisk.",
                )
            self.status_bar.showMessage("Tisk spuÅ¡tÄn nebo PDF otevÅeno.", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Chyba", f"Tisk selhal: {exc}")

    def _commit(self) -> None:
        try:
            self.db.commit()
            self.status_bar.showMessage("UloÅ¾eno.", 3000)
        except Exception as exc:
            QMessageBox.critical(self, "Chyba", f"UloÅ¾enÃ­ selhalo: {exc}")

    def _open_image_for_field(self, field_key: str) -> None:
        if not self.current_card:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Vyberte obrÃ¡zek",
            "",
            "ObrÃ¡zky (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;VÅ¡e (*.*)",
        )
        if not path:
            return
        try:
            pil = Image.open(path)
        except Exception as exc:
            QMessageBox.critical(self, "Chyba", f"NepodaÅilo se otevÅÃ­t obrÃ¡zek: {exc}")
            return

        layout_rect = self.preview.image_bounds.get(field_key)
        ratio: Optional[Tuple[int, int]] = None
        if layout_rect:
            ratio = (int(layout_rect.width()), int(layout_rect.height()))

        out_w, out_h = self.settings.output_size(ratio)
        png = edit_image_dialog(self, pil, (out_w, out_h))
        if png is None:
            return

        try:
            self.db.set_image(self.current_card.id, field_key, png)
            self.current_images = self.db.get_images_for_card(self.current_card.id)
            self.preview.set_card(self.current_card.name, self.current_images)
            self.status_bar.showMessage(f"UloÅ¾eno: {self.current_card.name} / {field_key}", 4000)
        except Exception as exc:
            QMessageBox.critical(self, "Chyba", f"UloÅ¾enÃ­ obrÃ¡zku selhalo: {exc}")

    def _clear_image_for_field(self, field_key: str) -> None:
        if not self.current_card:
            return
        resp = QMessageBox.question(
            self,
            "Vymazat",
            f"Opravdu vymazat obrÃ¡zek pro â{field_key}â?",
        )
        if resp == QMessageBox.Yes:
            try:
                self.db.clear_image(self.current_card.id, field_key)
                self.current_images = self.db.get_images_for_card(self.current_card.id)
                self.preview.set_card(self.current_card.name, self.current_images)
            except Exception as exc:
                QMessageBox.critical(self, "Chyba", f"VymazÃ¡nÃ­ selhalo: {exc}")


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    try:
        sys.exit(app.exec())
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    main()
