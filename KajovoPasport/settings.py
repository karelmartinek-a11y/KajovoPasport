"""
User settings storage for KajovoPasport.

Settings file: %APPDATA%\\KajovoPasport\\settings.json
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Tuple

APP_NAME = "KajovoPasport"
DEFAULT_RATIO = (2, 3)


def get_app_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    p = Path(appdata) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_db_path() -> Path:
    return get_app_dir() / "kajovopasport.db"


@dataclass
class Settings:
    db_path: str
    output_width_px: int = 800

    def output_size(self, layout_ratio: Optional[Tuple[int, int]] = None) -> Tuple[int, int]:
        ratio_w, ratio_h = layout_ratio or DEFAULT_RATIO
        ratio_w = max(1, ratio_w)
        ratio_h = max(1, ratio_h)
        out_w = int(self.output_width_px)
        out_h = int(round(out_w * (ratio_h / ratio_w)))
        return out_w, out_h


def settings_path() -> Path:
    return get_app_dir() / "settings.json"


def load_settings() -> Settings:
    sp = settings_path()
    if sp.exists():
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
            db_path = str(Path(data.get("db_path", str(default_db_path()))))
            output_width_px = int(data.get("output_width_px", 800))
            return Settings(db_path=db_path, output_width_px=output_width_px)
        except Exception:
            pass
    s = Settings(db_path=str(default_db_path()))
    save_settings(s)
    return s


def save_settings(s: Settings) -> None:
    sp = settings_path()
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8")
