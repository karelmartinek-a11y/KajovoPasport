from __future__ import annotations

import io
import os
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from PIL import Image, ImageTk

from .db import Database, Card, copy_db_file
from .settings import Settings, load_settings, save_settings, default_db_path
from .image_editor import edit_image_dialog
from .pdf_utils import generate_card_pdf, open_pdf, print_pdf_windows, make_temp_pdf_path

APP_TITLE = "KajovoPasport"

# Pozn.: v zadání je „13 miniatur“, ale seznam obsahuje 16 názvů – držíme se seznamu.
FIELDS: List[Tuple[str, str]] = [
    ("skrin", "skříň"),
    ("satna", "šatna"),
    ("stolek", "stolek"),
    ("okno_obyvak", "okno obývák"),
    ("tv", "tv"),
    ("svetla_obyvak", "světla obývák"),
    ("postel_1", "postel 1"),
    ("postel_2", "postel 2"),
    ("postel_3", "postel 3"),
    ("okno_koupelna", "okno koupelna"),
    ("wc", "wc"),
    ("umyvadlo", "umyvadlo"),
    ("sprcha", "sprcha"),
    ("koupelna_svetla", "koupelna světla"),
    ("dvere_vchod", "dveře vchod"),
    ("dvere_koupelna", "dveře koupelna"),
]

APP_BG = "#f4f6fb"
PREVIEW_BG = "#f9fbff"
ACCENT_COLOR = "#0f62fe"


def human_exception(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


class SettingsDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, settings: Settings):
        super().__init__(master)
        self.title("Nastavení")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)

        self._result: Optional[Settings] = None

        self.var_db = tk.StringVar(value=settings.db_path)
        self.var_ratio = tk.StringVar(value=settings.aspect_ratio)
        self.var_width = tk.IntVar(value=settings.output_width_px)

        frm = ttk.Frame(self, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Databáze (SQLite soubor):").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ent = ttk.Entry(frm, textvariable=self.var_db, width=50)
        ent.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        ttk.Button(frm, text="Vybrat…", command=self._browse_db).grid(row=0, column=2, padx=(8, 0), pady=(0, 6))

        ttk.Label(frm, text="Poměr ořezu (portrét):").grid(row=1, column=0, sticky="w", pady=(0, 6))
        cb = ttk.Combobox(frm, textvariable=self.var_ratio, state="readonly", values=["2:3", "3:4", "4:5"])
        cb.grid(row=1, column=1, sticky="w", pady=(0, 6))

        ttk.Label(frm, text="Šířka exportu (px):").grid(row=2, column=0, sticky="w", pady=(0, 6))
        sp = ttk.Spinbox(frm, from_=400, to=2400, increment=100, textvariable=self.var_width, width=10)
        sp.grid(row=2, column=1, sticky="w", pady=(0, 6))

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="Uložit", command=self._on_ok).grid(row=0, column=0, padx=4)
        ttk.Button(btns, text="Zrušit", command=self._on_cancel).grid(row=0, column=1, padx=4)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _browse_db(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Vyberte nebo vytvořte databázi",
            defaultextension=".db",
            filetypes=[("SQLite DB", "*.db *.sqlite *.sqlite3"), ("Vše", "*.*")],
            initialfile=Path(self.var_db.get()).name or "kajovopasport.db",
        )
        if path:
            self.var_db.set(path)

    def _on_ok(self) -> None:
        s = Settings(
            db_path=str(self.var_db.get()).strip() or str(default_db_path()),
            aspect_ratio=str(self.var_ratio.get()).strip() or "2:3",
            output_width_px=int(self.var_width.get()),
        )
        self._result = s
        self.destroy()

    def _on_cancel(self) -> None:
        self._result = None
        self.destroy()

    def result(self) -> Optional[Settings]:
        return self._result


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.configure(bg=APP_BG)

        # Maximalizovat na hlavním monitoru (Windows)
        try:
            self.root.state("zoomed")
        except Exception:
            pass

        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.style.configure("Header.TFrame", background=APP_BG)
        self.style.configure("Status.TLabel", background=APP_BG, foreground="#333333")
        self.style.configure(
            "Accent.TButton",
            foreground="white",
            background=ACCENT_COLOR,
            font=("Segoe UI", 9, "bold"),
            padding=6,
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", "#0a54c9"), ("pressed", "#084298")],
            relief=[("pressed", "sunken"), ("!pressed", "raised")],
        )

        self.settings = load_settings()
        self.db = Database(self.settings.db_path)

        self.cards: List[Card] = []
        self.current_card: Optional[Card] = None
        self.current_images: Dict[str, bytes] = {}

        # Preview assets
        self._thumb_photos: Dict[str, ImageTk.PhotoImage] = {}
        self._cell_boxes: List[Tuple[str, Tuple[int, int, int, int]]] = []  # field_key -> rect
        self._page_box: Tuple[int, int, int, int] = (0, 0, 0, 0)

        self._build_ui()
        self._bind_events()

        self.refresh_cards()
        self.select_first_card()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = ttk.Frame(self.root, padding=(12, 10, 12, 6), style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=0)
        header.columnconfigure(1, weight=1)
        header.columnconfigure(2, weight=0)

        ttk.Label(header, text=APP_TITLE, font=("Segoe UI SemiBold", 18), foreground="#111").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        ttk.Label(
            header,
            text="Profesionální tiskový pasport pro Kajovo",
            font=("Segoe UI", 10),
            foreground="#555",
        ).grid(row=1, column=0, sticky="w", padx=(0, 12))

        left_btns = ttk.Frame(header)
        left_btns.grid(row=0, column=1, sticky="w")
        ttk.Button(left_btns, text="Nastavení", command=self.on_settings).grid(row=0, column=0, padx=3)
        ttk.Button(left_btns, text="Load", command=self.on_load_db).grid(row=0, column=1, padx=3)
        ttk.Button(left_btns, text="Save", command=self.on_save_db_as).grid(row=0, column=2, padx=3)

        ttk.Button(header, text="Exit", command=self.on_exit).grid(row=0, column=2, sticky="e")
        ttk.Separator(self.root, orient="horizontal").grid(row=1, column=0, sticky="ew")

        # Main split
        main = ttk.Frame(self.root, padding=(10, 8))
        main.grid(row=2, column=0, sticky="nsew")
        main.columnconfigure(0, weight=0)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        # Left column: cards list
        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        left.rowconfigure(1, weight=1)

        ttk.Label(left, text="Pasportní karty", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")

        self.listbox = tk.Listbox(left, height=20, exportselection=False, font=("Segoe UI", 10), bg="white", bd=0, highlightthickness=0)
        self.listbox.grid(row=1, column=0, sticky="nsw")
        self.listbox.config(width=28)

        lb_scroll = ttk.Scrollbar(left, orient="vertical", command=self.listbox.yview)
        lb_scroll.grid(row=1, column=1, sticky="ns")
        self.listbox.config(yscrollcommand=lb_scroll.set)

        left_btns2 = ttk.Frame(left)
        left_btns2.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(left_btns2, text="Přidat", command=self.on_add_card).grid(row=0, column=0, padx=3)
        ttk.Button(left_btns2, text="Upravit", command=self.on_rename_card).grid(row=0, column=1, padx=3)
        ttk.Button(left_btns2, text="Smazat", command=self.on_delete_card).grid(row=0, column=2, padx=3)

        # Right column: preview + actions
        right = ttk.Frame(main)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(right, bg=PREVIEW_BG, highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        action_bar = ttk.Frame(right, padding=(0, 8, 0, 0))
        action_bar.grid(row=1, column=0, sticky="ew")
        action_bar.columnconfigure(0, weight=1)

        ttk.Button(action_bar, text="Upravit", command=self.on_rename_card).grid(row=0, column=0, padx=4, sticky="w")
        ttk.Button(action_bar, text="Uložit", command=self.on_commit).grid(row=0, column=1, padx=4, sticky="w")
        ttk.Button(action_bar, text="PDF", command=self.on_pdf, style="Accent.TButton").grid(
            row=0, column=2, padx=4, sticky="w"
        )
        ttk.Button(action_bar, text="Tisknout", command=self.on_print, style="Accent.TButton").grid(
            row=0, column=3, padx=4, sticky="w"
        )

        # Status bar
        self.status = tk.StringVar(value="")
        status_lbl = ttk.Label(self.root, textvariable=self.status, padding=(10, 6), style="Status.TLabel")
        status_lbl.grid(row=3, column=0, sticky="ew")

        # Context menu for clearing image
        self.cell_menu = tk.Menu(self.root, tearoff=0)
        self.cell_menu.add_command(label="Vymazat obrázek", command=self._clear_last_cell)
        self._last_clicked_field: Optional[str] = None

    def _bind_events(self) -> None:
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.on_list_select())
        self.listbox.bind("<Motion>", self.on_list_hover)
        self.listbox.bind("<Double-Button-1>", lambda e: self.on_rename_card())

        self.preview_canvas.bind("<Configure>", lambda e: self.render_preview())
        self.preview_canvas.bind("<Button-1>", self.on_preview_click)
        self.preview_canvas.bind("<Button-3>", self.on_preview_right_click)

    # ---------------------------
    # Data/UI refresh
    # ---------------------------
    def refresh_cards(self) -> None:
        self.cards = self.db.list_cards()
        self.listbox.delete(0, tk.END)
        for c in self.cards:
            self.listbox.insert(tk.END, c.name)

    def select_first_card(self) -> None:
        if not self.cards:
            self.current_card = None
            self.current_images = {}
            self.render_preview()
            return
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(0)
        self.listbox.activate(0)
        self.on_list_select()

    def _find_card_by_name(self, name: str) -> Optional[Card]:
        for c in self.cards:
            if c.name == name:
                return c
        return None

    def on_list_select(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        card = self._find_card_by_name(name)
        if not card:
            return
        self.current_card = card
        self.current_images = self.db.get_images_for_card(card.id)
        self.render_preview()

    def on_list_hover(self, event: tk.Event) -> None:
        idx = self.listbox.nearest(event.y)
        if idx is None:
            return
        if idx < 0 or idx >= self.listbox.size():
            return
        cur = self.listbox.curselection()
        if cur and cur[0] == idx:
            return
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(idx)
        self.listbox.activate(idx)
        self.on_list_select()

    # ---------------------------
    # Card operations
    # ---------------------------
    def on_add_card(self) -> None:
        name = simpledialog.askstring("Nová karta", "Zadejte název pasportní karty:", parent=self.root)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        try:
            self.db.create_card(name)
            self.refresh_cards()
            # select new
            for i in range(self.listbox.size()):
                if self.listbox.get(i) == name:
                    self.listbox.selection_clear(0, tk.END)
                    self.listbox.selection_set(i)
                    self.listbox.activate(i)
                    break
            self.on_list_select()
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodařilo se vytvořit kartu: {human_exception(e)}")

    def on_rename_card(self) -> None:
        if not self.current_card:
            return
        new_name = simpledialog.askstring("Upravit kartu", "Nový název:", initialvalue=self.current_card.name, parent=self.root)
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        try:
            self.db.rename_card(self.current_card.id, new_name)
            self.refresh_cards()
            for i in range(self.listbox.size()):
                if self.listbox.get(i) == new_name:
                    self.listbox.selection_clear(0, tk.END)
                    self.listbox.selection_set(i)
                    self.listbox.activate(i)
                    break
            self.on_list_select()
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodařilo se přejmenovat kartu: {human_exception(e)}")

    def on_delete_card(self) -> None:
        if not self.current_card:
            return
        if not messagebox.askyesno("Smazat", f"Opravdu smazat kartu „{self.current_card.name}“?"):
            return
        try:
            cid = self.current_card.id
            self.db.delete_card(cid)
            self.refresh_cards()
            self.select_first_card()
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodařilo se smazat kartu: {human_exception(e)}")

    # ---------------------------
    # Header operations
    # ---------------------------
    def on_settings(self) -> None:
        dlg = SettingsDialog(self.root, self.settings)
        dlg.wait_window()
        res = dlg.result()
        if not res:
            return

        db_changed = Path(res.db_path) != Path(self.settings.db_path)
        self.settings = res
        save_settings(self.settings)

        if db_changed:
            self._reopen_db(self.settings.db_path)
        self.render_preview()

    def _reopen_db(self, path: str) -> None:
        try:
            self.db.close()
        except Exception:
            pass
        self.db = Database(path)
        self.refresh_cards()
        self.select_first_card()
        self.status.set(f"Otevřena databáze: {path}")

    def on_load_db(self) -> None:
        path = filedialog.askopenfilename(
            title="Load databáze",
            filetypes=[("SQLite DB", "*.db *.sqlite *.sqlite3"), ("Vše", "*.*")],
        )
        if not path:
            return
        self.settings.db_path = path
        save_settings(self.settings)
        self._reopen_db(path)

    def on_save_db_as(self) -> None:
        if not Path(self.settings.db_path).exists():
            messagebox.showwarning("Upozornění", "Aktuální databáze neexistuje.")
            return
        dst = filedialog.asksaveasfilename(
            title="Save databáze jako…",
            defaultextension=".db",
            filetypes=[("SQLite DB", "*.db"), ("Vše", "*.*")],
            initialfile=Path(self.settings.db_path).name,
        )
        if not dst:
            return
        try:
            copy_db_file(self.settings.db_path, dst)
            self.status.set(f"Uloženo: {dst}")
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodařilo se uložit kopii: {human_exception(e)}")

    def on_exit(self) -> None:
        self.root.destroy()

    # ---------------------------
    # Right panel actions
    # ---------------------------
    def on_commit(self) -> None:
        try:
            self.db.commit()
            self.status.set("Uloženo.")
        except Exception as e:
            messagebox.showerror("Chyba", f"Uložení selhalo: {human_exception(e)}")

    def on_pdf(self) -> None:
        if not self.current_card:
            return
        try:
            pdf_path = make_temp_pdf_path(self.current_card.name)
            images = self.db.get_images_for_card(self.current_card.id)
            generate_card_pdf(pdf_path, self.current_card.name, FIELDS, images)
            open_pdf(pdf_path)
            self.status.set(f"PDF vytvořeno: {pdf_path}")
        except Exception as e:
            messagebox.showerror("Chyba", f"PDF selhalo: {human_exception(e)}")

    def on_print(self) -> None:
        if not self.current_card:
            return
        try:
            pdf_path = make_temp_pdf_path(self.current_card.name)
            images = self.db.get_images_for_card(self.current_card.id)
            generate_card_pdf(pdf_path, self.current_card.name, FIELDS, images)
            ok = print_pdf_windows(pdf_path)
            if not ok:
                open_pdf(pdf_path)
                messagebox.showinfo(
                    "Tisk",
                    "Nepodařilo se spustit tisk automaticky.\n"
                    "Otevírám PDF – vytiskněte ho prosím ručně z prohlížeče.",
                )
            self.status.set("Tisk spuštěn (nebo otevřeno PDF).")
        except Exception as e:
            messagebox.showerror("Chyba", f"Tisk selhal: {human_exception(e)}")

    # ---------------------------
    # Preview rendering / interaction
    # ---------------------------
    def render_preview(self) -> None:
        c = self.preview_canvas
        cw = max(1, int(c.winfo_width()))
        ch = max(1, int(c.winfo_height()))
        c.delete("all")
        self._thumb_photos = {}
        self._cell_boxes = []
        self._last_clicked_field = None

        c.create_rectangle(0, 0, cw, ch, fill="#ececec", outline="")

        # A4 portrait ratio
        a4_ratio = 210 / 297  # width/height
        pad = 20
        avail_w = max(1, cw - 2 * pad)
        avail_h = max(1, ch - 2 * pad)

        page_h = avail_h
        page_w = int(round(page_h * a4_ratio))
        if page_w > avail_w:
            page_w = avail_w
            page_h = int(round(page_w / a4_ratio))

        px0 = (cw - page_w) // 2
        py0 = (ch - page_h) // 2
        px1 = px0 + page_w
        py1 = py0 + page_h
        self._page_box = (px0, py0, px1, py1)

        c.create_rectangle(px0, py0, px1, py1, fill="white", outline="#666666", width=2)

        margin = max(8, int(round(page_w * 0.03)))
        ix0 = px0 + margin
        iy0 = py0 + margin
        ix1 = px1 - margin
        iy1 = py1 - margin

        title = self.current_card.name if self.current_card else "(žádná karta)"
        c.create_text(ix0, iy0, anchor="nw", text=title, font=("Segoe UI", 14, "bold"), fill="black")

        title_h = 30
        grid_top = iy0 + title_h + 6
        grid_bottom = iy1
        grid_h = max(1, grid_bottom - grid_top)
        grid_w = max(1, ix1 - ix0)

        cols = 4
        rows = 4
        gap = max(6, int(round(page_w * 0.015)))

        cell_w = (grid_w - gap * (cols - 1)) // cols
        cell_h = (grid_h - gap * (rows - 1)) // rows

        label_h = max(16, int(cell_h * 0.18))
        img_pad = 6

        images = self.current_images if self.current_card else {}
        for idx, (field_key, label) in enumerate(FIELDS):
            r = idx // cols
            col = idx % cols

            x = ix0 + col * (cell_w + gap)
            y = grid_top + r * (cell_h + gap)
            x2 = x + cell_w
            y2 = y + cell_h

            c.create_rectangle(x, y, x2, y2, outline="#999999", width=1)

            c.create_rectangle(x, y2 - label_h, x2, y2, outline="", fill="#f7f7f7")
            c.create_text(x + 6, y2 - label_h + 2, anchor="nw", text=label, font=("Segoe UI", 9), fill="black")

            img_x0 = x + img_pad
            img_y0 = y + img_pad
            img_x1 = x2 - img_pad
            img_y1 = y2 - label_h - img_pad

            c.create_rectangle(img_x0, img_y0, img_x1, img_y1, outline="#cccccc", width=1, fill="white")

            png_bytes = images.get(field_key)
            if png_bytes:
                try:
                    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
                    tw = max(1, img_x1 - img_x0)
                    th = max(1, img_y1 - img_y0)
                    iw, ih = im.size
                    scale = min(tw / iw, th / ih)
                    nw = max(1, int(round(iw * scale)))
                    nh = max(1, int(round(ih * scale)))
                    thumb = im.resize((nw, nh), resample=Image.LANCZOS)
                    photo = ImageTk.PhotoImage(thumb)
                    self._thumb_photos[field_key] = photo
                    cx = img_x0 + (tw - nw) // 2
                    cy = img_y0 + (th - nh) // 2
                    c.create_image(cx, cy, anchor="nw", image=photo)
                except Exception:
                    pass

            self._cell_boxes.append((field_key, (x, y, x2, y2)))

        if not self.current_card:
            c.create_text((px0 + px1) // 2, (py0 + py1) // 2, text="Vlevo vytvořte/přidejte kartu.", font=("Segoe UI", 12), fill="#666666")

    def _field_at_point(self, x: int, y: int) -> Optional[str]:
        for field_key, (x0, y0, x1, y1) in self._cell_boxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return field_key
        return None

    def on_preview_click(self, event: tk.Event) -> None:
        if not self.current_card:
            return
        field_key = self._field_at_point(event.x, event.y)
        if not field_key:
            return
        self._last_clicked_field = field_key
        self._select_image_for_field(field_key)

    def on_preview_right_click(self, event: tk.Event) -> None:
        if not self.current_card:
            return
        field_key = self._field_at_point(event.x, event.y)
        if not field_key:
            return
        self._last_clicked_field = field_key
        try:
            self.cell_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.cell_menu.grab_release()

    def _clear_last_cell(self) -> None:
        if not self.current_card or not self._last_clicked_field:
            return
        fk = self._last_clicked_field
        if not messagebox.askyesno("Vymazat", f"Vymazat obrázek pro „{fk}“?"):
            return
        try:
            self.db.clear_image(self.current_card.id, fk)
            self.current_images = self.db.get_images_for_card(self.current_card.id)
            self.render_preview()
        except Exception as e:
            messagebox.showerror("Chyba", f"Vymazání selhalo: {human_exception(e)}")

    def _select_image_for_field(self, field_key: str) -> None:
        path = filedialog.askopenfilename(
            title="Vyberte obrázek",
            filetypes=[
                ("Obrázky", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"),
                ("Vše", "*.*"),
            ],
        )
        if not path:
            return

        try:
            pil = Image.open(path)
        except Exception as e:
            messagebox.showerror("Chyba", f"Nelze otevřít obrázek: {human_exception(e)}")
            return

        out_w, out_h = self.settings.output_size
        png = edit_image_dialog(self.root, pil, (out_w, out_h))
        if png is None:
            return

        try:
            self.db.set_image(self.current_card.id, field_key, png)
            self.current_images = self.db.get_images_for_card(self.current_card.id)
            self.render_preview()
            self.status.set(f"Uloženo: {self.current_card.name} / {field_key}")
        except Exception as e:
            messagebox.showerror("Chyba", f"Uložení obrázku selhalo: {human_exception(e)}")


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass

    try:
        if sys.platform.startswith("win"):
            root.tk.call("tk", "scaling", 1.2)
    except Exception:
        pass

    try:
        App(root)
        root.mainloop()
    except Exception as e:
        try:
            messagebox.showerror("Chyba", f"Aplikace spadla:\n{human_exception(e)}")
        except Exception:
            pass
        traceback.print_exc()
        try:
            root.destroy()
        except Exception:
            pass
