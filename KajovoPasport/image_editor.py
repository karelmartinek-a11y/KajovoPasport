from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Optional, Tuple

import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk


@dataclass
class TransformState:
    zoom: float = 1.0           # user zoom multiplier
    angle_deg: int = 0          # rotation in degrees
    offset_x: float = 0.0       # in output pixels
    offset_y: float = 0.0       # in output pixels


class ImageEditor(tk.Toplevel):
    """
    Simple portrait crop editor:
    - fixed crop aspect (output_size)
    - drag to move image
    - mouse wheel to zoom
    - rotate buttons
    """
    def __init__(self, master: tk.Misc, pil_image: Image.Image, output_size: Tuple[int, int], title: str = "Upravit obrázek"):
        super().__init__(master)
        self.title(title)
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()
        self.geometry("960x720")
        self.minsize(900, 640)

        self.original = pil_image.convert("RGBA")
        self.out_w, self.out_h = output_size
        self.state = TransformState()

        # base scale to cover crop area
        ow, oh = self.original.size
        self.base_scale = max(self.out_w / max(1, ow), self.out_h / max(1, oh))

        self._drag_start = None  # (x, y, ox, oy)
        self._pending_render = None
        self._preview_photo = None

        self._build_ui()
        self._bind_events()

        self._result_png: Optional[bytes] = None
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self.after(10, self._render)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="nsew")
        top.columnconfigure(0, weight=1)
        top.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(top, bg="#f0f0f0", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        controls = ttk.Frame(self, padding=(12, 10, 12, 12))
        controls.grid(row=1, column=0, sticky="ew")
        for col in range(6):
            controls.columnconfigure(col, weight=1)

        ttk.Label(
            controls,
            text="Formát: táhněte obrázek, kolečko pro zoom, tlačítka pro rotaci a lupa pro zvětšení.",
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))

        ttk.Button(controls, text="⟲ -90°", command=lambda: self._rotate(-90)).grid(row=1, column=0, padx=4)
        ttk.Button(controls, text="⟳ +90°", command=lambda: self._rotate(+90)).grid(row=1, column=1, padx=4)
        ttk.Button(controls, text="↺ -5°", command=lambda: self._rotate(-5)).grid(row=1, column=2, padx=4)
        ttk.Button(controls, text="↻ +5°", command=lambda: self._rotate(+5)).grid(row=1, column=3, padx=4)
        ttk.Button(controls, text="Reset", command=self._reset).grid(row=1, column=4, padx=4)

        zoom_frame = ttk.Frame(controls)
        zoom_frame.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(8, 6))
        zoom_frame.columnconfigure(0, weight=0)
        zoom_frame.columnconfigure(1, weight=1)
        zoom_frame.columnconfigure(2, weight=0)

        ttk.Button(zoom_frame, text="🔍 -", command=lambda: self._zoom(1 / 1.2)).grid(row=0, column=0, padx=(0, 6))
        self.zoom_slider = ttk.Scale(
            zoom_frame,
            from_=0.3,
            to=5.0,
            orient="horizontal",
            variable=self.zoom_var,
            command=self._on_slider_change,
        )
        self.zoom_slider.grid(row=0, column=1, sticky="ew")
        ttk.Button(zoom_frame, text="🔍 +", command=lambda: self._zoom(1.2)).grid(row=0, column=2, padx=(6, 0))

        ttk.Button(controls, text="Uložit", command=self._on_save).grid(row=3, column=4, padx=4, pady=(4, 0))
        ttk.Button(controls, text="Zrušit", command=self._on_cancel).grid(row=3, column=5, padx=4, pady=(4, 0))

    def _bind_events(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)

        # Windows mousewheel
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        # trackpad / some X11
        self.canvas.bind("<Button-4>", lambda e: self._zoom(1.1))
        self.canvas.bind("<Button-5>", lambda e: self._zoom(1/1.1))

        self.bind("<Configure>", lambda e: self._schedule_render())

    def _on_slider_change(self, value: str) -> None:
        try:
            zoom_value = float(value)
        except ValueError:
            return
        self.state.zoom = max(0.3, min(5.0, zoom_value))
        self._schedule_render()

    def _schedule_render(self) -> None:
        if self._pending_render is not None:
            return
        self._pending_render = self.after(30, self._render)

    def _render(self) -> None:
        if self._pending_render is not None:
            try:
                self.after_cancel(self._pending_render)
            except Exception:
                pass
            self._pending_render = None

        cw = max(1, int(self.canvas.winfo_width()))
        ch = max(1, int(self.canvas.winfo_height()))
        # Determine crop rect in canvas with same aspect as output
        target_aspect = self.out_w / self.out_h
        pad = 20
        avail_w = max(1, cw - 2 * pad)
        avail_h = max(1, ch - 2 * pad)
        if avail_w / avail_h > target_aspect:
            crop_h = avail_h
            crop_w = int(round(crop_h * target_aspect))
        else:
            crop_w = avail_w
            crop_h = int(round(crop_w / target_aspect))

        self.crop_rect = (
            (cw - crop_w) // 2,
            (ch - crop_h) // 2,
            (cw + crop_w) // 2,
            (ch + crop_h) // 2,
        )
        x0, y0, x1, y1 = self.crop_rect

        # Create preview by rendering final output and downscaling to crop rect size
        out_img = self._render_output_image()
        preview = out_img.resize((crop_w, crop_h), resample=Image.LANCZOS)

        self._preview_photo = ImageTk.PhotoImage(preview)
        self.canvas.delete("all")

        # Darken outside crop rect
        self.canvas.create_rectangle(0, 0, cw, y0, fill="#d0d0d0", outline="")
        self.canvas.create_rectangle(0, y1, cw, ch, fill="#d0d0d0", outline="")
        self.canvas.create_rectangle(0, y0, x0, y1, fill="#d0d0d0", outline="")
        self.canvas.create_rectangle(x1, y0, cw, y1, fill="#d0d0d0", outline="")

        # Crop outline
        self.canvas.create_rectangle(x0, y0, x1, y1, outline="black", width=2)

        # Image
        self.canvas.create_image((x0 + x1) // 2, (y0 + y1) // 2, image=self._preview_photo)

    def _render_output_image(self) -> Image.Image:
        """Render transformed image into output canvas (white background)."""
        # White background
        base = Image.new("RGBA", (self.out_w, self.out_h), (255, 255, 255, 255))

        ow, oh = self.original.size
        total_scale = self.base_scale * self.state.zoom
        sw = max(1, int(round(ow * total_scale)))
        sh = max(1, int(round(oh * total_scale)))

        # Resize first (usually faster than rotate first)
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

        # Place rotated image centered at (cx, cy)
        left = int(round(cx - rw / 2))
        top = int(round(cy - rh / 2))

        tmp = Image.new("RGBA", (self.out_w, self.out_h), (0, 0, 0, 0))
        tmp.paste(rotated, (left, top), rotated)
        base = Image.alpha_composite(base, tmp)
        return base

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_start = (event.x, event.y, self.state.offset_x, self.state.offset_y)

    def _on_drag_move(self, event: tk.Event) -> None:
        if not self._drag_start:
            return
        x0, y0, ox, oy = self._drag_start
        dx = event.x - x0
        dy = event.y - y0

        # Convert canvas pixels to output pixels using crop rect mapping
        cx0, cy0, cx1, cy1 = getattr(self, "crop_rect", (0, 0, 1, 1))
        crop_w = max(1, (cx1 - cx0))
        crop_h = max(1, (cy1 - cy0))
        scale = self.out_w / crop_w  # output pixels per canvas pixel

        self.state.offset_x = ox + dx * scale
        self.state.offset_y = oy + dy * (self.out_h / crop_h)
        self._schedule_render()

    def _on_drag_end(self, event: tk.Event) -> None:
        self._drag_start = None

    def _on_mousewheel(self, event: tk.Event) -> None:
        # event.delta on Windows: 120 per notch
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return
        steps = delta / 120.0
        factor = 1.1 ** steps
        self._zoom(factor)

    def _zoom(self, factor: float) -> None:
        self.state.zoom = float(max(0.2, min(8.0, self.state.zoom * factor)))
        if hasattr(self, "zoom_slider"):
            self.zoom_var.set(self.state.zoom)
            self.zoom_slider.set(self.state.zoom)
        self._schedule_render()

    def _rotate(self, deg: int) -> None:
        self.state.angle_deg = int((self.state.angle_deg + deg) % 360)
        self._schedule_render()

    def _reset(self) -> None:
        self.state = TransformState()
        self._schedule_render()

    def _on_save(self) -> None:
        try:
            out = self._render_output_image().convert("RGB")
            bio = io.BytesIO()
            out.save(bio, format="PNG")
            self._result_png = bio.getvalue()
            self.destroy()
        except Exception as e:
            messagebox.showerror("Chyba", f"Nepodařilo se uložit obrázek: {e}")

    def _on_cancel(self) -> None:
        self._result_png = None
        self.destroy()

    def get_result(self) -> Optional[bytes]:
        return self._result_png


def edit_image_dialog(master: tk.Misc, pil_image: Image.Image, output_size: Tuple[int, int]) -> Optional[bytes]:
    dlg = ImageEditor(master, pil_image, output_size)
    dlg.wait_window()
    return dlg.get_result()
