"""
ui/startup_menu.py
Pre-game startup menu — text-based, works before any renderer initialises.

Returns a dict:
  {
    "action":  "resume" | "new" | "editor" | "quit",
    "config":  cfg dict (possibly modified by model selection),
  }
"""

import sys
import requests
from pathlib import Path


_BANNER = r"""
  ╔══════════════════════════════════════════════╗
  ║   //  M O R I A R T Y                       ║
  ║   A locally-running AI creature.             ║
  ╚══════════════════════════════════════════════╝
"""

_DIVIDER = "  " + "─" * 46


def _ollama_models() -> list[str]:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def _pick_model(current: str) -> str:
    """Let the user select from available Ollama models. Returns chosen model."""
    print("\n  Querying Ollama for available models...")
    models = _ollama_models()
    if not models:
        print("  [!] Could not reach Ollama (is it running?)")
        print(f"  Keeping current model: {current}")
        input("  Press Enter to continue.")
        return current

    print(f"\n  Available models (current: {current}):\n")
    for i, m in enumerate(models, 1):
        marker = " ◀" if m == current else ""
        print(f"    {i}. {m}{marker}")
    print(f"    0. Keep current ({current})")
    print()

    while True:
        choice = input("  Select model [0]: ").strip()
        if choice == "" or choice == "0":
            return current
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                chosen = models[idx]
                print(f"  Model set to: {chosen}")
                return chosen
        except ValueError:
            pass
        print("  Invalid choice.")


def show(cfg: dict, save_info: dict | None) -> dict:
    """
    Display the startup menu and return the user's choice.

    cfg:       current config dict
    save_info: dict with 'tick', 'saved_at' if a save exists, else None
    """
    while True:
        print(_BANNER)
        print(f"  Model: {cfg['model']}   Seed: {cfg['seed']}")
        print(_DIVIDER)
        print()

        if save_info:
            ts = save_info.get("saved_at", "?")[:16].replace("T", " ")
            print(f"  1.  Resume world          (tick {save_info['tick']:,} — saved {ts})")
        else:
            print("  1.  Resume world          [no save found]")

        print("  2.  New world")
        print("  3.  Map editor            [coming soon]")
        print(f"  4.  Change model          [{cfg['model']}]")
        print("  5.  Quit")
        print()
        print(_DIVIDER)

        choice = input("  Choice [1]: ").strip() or "1"

        if choice == "1":
            if save_info:
                return {"action": "resume", "config": cfg}
            print("\n  No save file found — starting a new world.\n")
            return {"action": "new", "config": cfg}

        elif choice == "2":
            seed_str = input(f"  World seed [{cfg['seed']}]: ").strip()
            if seed_str:
                try:
                    cfg["seed"] = int(seed_str)
                except ValueError:
                    print("  Invalid seed — using previous.")
            return {"action": "new", "config": cfg}

        elif choice == "3":
            print("\n  Map editor coming soon — not yet implemented.\n")
            # Loop back to menu
            continue

        elif choice == "4":
            cfg["model"] = _pick_model(cfg["model"])
            from .. import config as _cfg_mod
            _cfg_mod.save(cfg)
            print(f"  Config saved.\n")
            # Loop back to updated menu

        elif choice == "5":
            return {"action": "quit", "config": cfg}

        else:
            print("  Invalid choice.\n")
