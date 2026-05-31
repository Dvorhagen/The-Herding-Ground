"""
ui/startup_menu.py
Pre-game startup menu — text-based, works before any renderer initialises.

Returns a dict:
  {
    "action":  "resume" | "new" | "editor" | "quit",
    "config":  cfg dict (possibly modified),
  }
"""

import requests

_BANNER = r"""
  ╔══════════════════════════════════════════════╗
  ║   //  M O R I A R T Y                       ║
  ║   A locally-running AI creature.             ║
  ╚══════════════════════════════════════════════╝
"""
_DIVIDER = "  " + "─" * 46

TICK_DELAYS  = [0, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]
_SPEED_NAMES = ["instant", "0.25s", "0.5s", "1.0s", "2.0s", "5.0s", "10.0s"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ollama_models() -> list[str]:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def _speed_label(cfg: dict) -> str:
    if cfg.get("default_stepped"):
        return "Step (manual)"
    idx = cfg.get("tick_delay_idx", 3)
    return _SPEED_NAMES[idx] if 0 <= idx < len(_SPEED_NAMES) else "1.0s"


def _pick_model(current: str) -> str:
    print("\n  Querying Ollama for available models...")
    models = _ollama_models()
    if not models:
        print("  [!] Could not reach Ollama.")
        input("  Press Enter to continue.")
        return current
    print(f"\n  Available models (current: {current}):\n")
    for i, m in enumerate(models, 1):
        marker = " ◀" if m == current else ""
        print(f"    {i}. {m}{marker}")
    print(f"    0. Keep current ({current})")
    print()
    while True:
        choice = input("  Select [0]: ").strip()
        if not choice or choice == "0":
            return current
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                print(f"  Model → {models[idx]}")
                return models[idx]
        except ValueError:
            pass
        print("  Invalid.")


def _configure(cfg: dict) -> dict:
    """Configure submenu. Returns modified cfg."""
    from .. import config as _cfg_mod
    while True:
        print(f"\n  CONFIGURE")
        print(_DIVIDER)
        print(f"  1.  Change model    [{cfg['model']}]")
        print(f"  2.  Default speed   [{_speed_label(cfg)}]")
        print(f"  3.  World seed      [{cfg['seed']}]")
        print(f"  4.  Back")
        print()
        choice = input("  Choice [4]: ").strip() or "4"

        if choice == "1":
            cfg["model"] = _pick_model(cfg["model"])
            _cfg_mod.save(cfg)
            print("  Saved.\n")

        elif choice == "2":
            print("\n  Default run speed:")
            for i, name in enumerate(_SPEED_NAMES):
                marker = " ◀" if (not cfg.get("default_stepped") and
                                   cfg.get("tick_delay_idx", 3) == i) else ""
                print(f"    {i}. {name}{marker}")
            step_marker = " ◀" if cfg.get("default_stepped") else ""
            print(f"    S. Step (manual advance){step_marker}")
            print(f"    0. Keep current")
            pick = input("  Choice [0]: ").strip().lower()
            if pick and pick != "0":
                if pick == "s":
                    cfg["default_stepped"] = True
                    print("  Default: Step mode.")
                else:
                    try:
                        idx = int(pick)
                        if 0 <= idx < len(TICK_DELAYS):
                            cfg["tick_delay_idx"] = idx
                            cfg["default_stepped"] = False
                            print(f"  Default speed: {_SPEED_NAMES[idx]}")
                    except ValueError:
                        print("  Invalid.")
            _cfg_mod.save(cfg)

        elif choice == "3":
            seed_str = input(f"  World seed [{cfg['seed']}]: ").strip()
            if seed_str:
                try:
                    cfg["seed"] = int(seed_str)
                    _cfg_mod.save(cfg)
                    print(f"  Seed → {cfg['seed']}")
                except ValueError:
                    print("  Invalid seed.")

        elif choice == "4":
            return cfg

        else:
            print("  Invalid.")


# ── Main menu ─────────────────────────────────────────────────────────────────

def show(cfg: dict, save_info: dict | None) -> dict:
    """Show startup menu, return user's choice + (possibly modified) config."""
    while True:
        print(_BANNER)
        print(f"  Model: {cfg['model']}   Seed: {cfg['seed']}   "
              f"Speed: {_speed_label(cfg)}")
        print(_DIVIDER)
        print()

        if save_info:
            ts = save_info.get("saved_at", "?")[:16].replace("T", " ")
            print(f"  1.  Resume world     (tick {save_info['tick']:,} — saved {ts})")
        else:
            print("  1.  Resume world     [no save found]")

        print("  2.  New world")
        print("  3.  Map editor       [coming soon]")
        print("  4.  Configure")
        print("  5.  Quit")
        print()
        print(_DIVIDER)
        choice = input("  Choice [1]: ").strip() or "1"

        if choice == "1":
            if save_info:
                return {"action": "resume", "config": cfg}
            print("\n  No save — starting a new world.\n")
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
            print("\n  Map editor not yet implemented.\n")

        elif choice == "4":
            cfg = _configure(cfg)

        elif choice == "5":
            return {"action": "quit", "config": cfg}

        else:
            print("  Invalid.\n")
