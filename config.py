"""
config.py
Project-level configuration: model, world seed, tick speed, renderer.
Persists to save/config.json independently of the world save.
"""

import json
from pathlib import Path

_SAVE_DIR   = Path(__file__).parent / "save"
CONFIG_FILE = _SAVE_DIR / "config.json"
SAVE_FILE   = _SAVE_DIR / "world.json"

DEFAULTS = {
    "model":          "qwen3.5:4b",
    "seed":           42,
    "tick_delay_idx": 3,
    "renderer":       "auto",   # "auto" | "pygame" | "curses"
}


def load() -> dict:
    if CONFIG_FILE.exists():
        try:
            stored = json.loads(CONFIG_FILE.read_text())
            return {**DEFAULTS, **stored}
        except Exception:
            pass
    return dict(DEFAULTS)


def save(cfg: dict):
    _SAVE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
