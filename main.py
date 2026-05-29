"""
main.py — Nemo world engine entry point.

Controls (Aaron mode):
  Arrow keys / WASD / hjkl : move
  P: pickup   E: examine   . : wait   TAB: toggle control   Q: quit

Renderer auto-detected:
  - Display available (DISPLAY/WAYLAND_DISPLAY set, or macOS) -> pygame
  - No display (SSH without X) -> curses
  - Force curses: NEMO_RENDERER=curses python main.py
"""

import sys
import os
import threading
import logging

# ── Display auto-detection ────────────────────────────────────────────────────
def _has_display() -> bool:
    if sys.platform == "darwin":
        return True
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True
    return False

USE_CURSES = (not _has_display()) or os.environ.get("NEMO_RENDERER") == "curses"

# Only import pygame when we actually need it
if not USE_CURSES:
    import pygame

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nemo.world.mapgen import generate_world, find_spawn
from nemo.world.state import WorldState
from nemo.entities.base import NemoEntity, EntityType
from nemo.entities.items import make_apple, make_stick
from nemo.entities.actions import resolve_action, ActionResult
from nemo.brain import nemo_brain
from nemo.memory import wiki

log = logging.getLogger("nemo")

# ── Pygame key map (only used when pygame is active) ─────────────────────────
def _make_pygame_keymap():
    return {
        pygame.K_UP:     ("move", {"direction": "north"}),
        pygame.K_DOWN:   ("move", {"direction": "south"}),
        pygame.K_LEFT:   ("move", {"direction": "west"}),
        pygame.K_RIGHT:  ("move", {"direction": "east"}),
        pygame.K_w:      ("move", {"direction": "north"}),
        pygame.K_s:      ("move", {"direction": "south"}),
        pygame.K_a:      ("move", {"direction": "west"}),
        pygame.K_d:      ("move", {"direction": "east"}),
        pygame.K_k:      ("move", {"direction": "north"}),
        pygame.K_j:      ("move", {"direction": "south"}),
        pygame.K_h:      ("move", {"direction": "west"}),
        pygame.K_l:      ("move", {"direction": "east"}),
        pygame.K_y:      ("move", {"direction": "nw"}),
        pygame.K_u:      ("move", {"direction": "ne"}),
        pygame.K_b:      ("move", {"direction": "sw"}),
        pygame.K_n:      ("move", {"direction": "se"}),
        pygame.K_p:      ("pickup", {}),
        pygame.K_e:      ("examine", {"target": "surroundings"}),
        pygame.K_PERIOD: ("wait", {}),
    }

# ── Shared helpers ────────────────────────────────────────────────────────────

def nemo_think_async(world_state, result_holder):
    """Run Nemo's brain in a background thread so the UI stays responsive."""
    perception = world_state.build_perception_block()
    action_dict = nemo_brain.think(perception)
    result_holder.append(action_dict)


def apply_action(action_name, args, actor, world_state, renderer):
    """Execute one action and push the result message to the renderer."""
    result = resolve_action(action_name, args, actor, world_state)
    renderer.add_message(result.message)
    actor.log_event(result.message)
    log.info(f"GAME action={action_name} args={args} ok={result.success} | {result.message[:80]}")
    if result.data and result.data.get("trigger_reflection"):
        _handle_reflection(actor, world_state, renderer)
    return result


def _handle_reflection(nemo, world_state, renderer):
    renderer.add_message("[Nemo is reflecting...]")
    perception = world_state.build_perception_block()
    self_model = wiki.get_self_model()
    prompt = (
        "You are reflecting on your experience so far.\n\n"
        f"Current self-model:\n{self_model}\n\n"
        f"Current perception:\n{perception}\n\n"
        "Update your self-model. Be honest. Be specific. Do not perform.\n"
        "Write only the markdown content -- nothing else."
    )
    messages = [
        {"role": "system", "content": "You are Nemo. Reflect honestly."},
        {"role": "user",   "content": prompt},
    ]
    response = nemo_brain.call_ollama(messages, thinking=True, timeout=60)
    if response:
        wiki.update_self_model(response)
        renderer.add_message("[Self-model updated.]")
        nemo.log_event("Reflected and updated self-model.")


def _process_nemo_result(action_dict, nemo, world_state, renderer):
    """Handle one brain tick result: log thought, execute action, record event."""
    if action_dict["thought"]:
        renderer.last_thought = action_dict["thought"]
        nemo.log_event(f"[THOUGHT] {action_dict['thought']}")

    log.info(f"LOOP tick={world_state.tick} action={action_dict['action']} args={action_dict['args']}")

    if action_dict["memory_tool"]:
        mem_result = wiki.execute_memory_tool(action_dict["memory_tool"])
        world_state.pending_memory_result = mem_result
        renderer.add_message(f"[MEM] {mem_result[:80]}")

    result = apply_action(action_dict["action"], action_dict["args"],
                          nemo, world_state, renderer)
    if result.world_changed:
        world_state.advance_tick()
        renderer.center_on(nemo.x, nemo.y)


def _init_world():
    """Build the world, spawn Nemo, scatter starting items."""
    print("[NEMO] Generating world...")
    world = generate_world(width=512, height=512, seed=42)
    spawn_x, spawn_y = find_spawn(world)

    nemo = NemoEntity(name="Nemo", entity_type=EntityType.NEMO,
                      x=spawn_x, y=spawn_y)
    world_state = WorldState(world=world, nemo=nemo)

    def safe_item(make_fn, dx, dy):
        x = max(0, min(world.width  - 1, spawn_x + dx))
        y = max(0, min(world.height - 1, spawn_y + dy))
        for ox, oy in [(0,0),(1,0),(-1,0),(0,1),(0,-1)]:
            tx, ty = x + ox, y + oy
            if world.is_passable(tx, ty):
                return make_fn(tx, ty)
        return make_fn(x, y)

    world_state.add_entity(safe_item(make_apple,  1,  0))
    world_state.add_entity(safe_item(make_apple,  2,  1))
    world_state.add_entity(safe_item(make_apple, -1,  2))
    world_state.add_entity(safe_item(make_stick,  1, -1))
    nemo.status.hunger = 80

    wiki._ensure_dirs()
    wiki.get_self_model()

    return world_state, spawn_x, spawn_y

# ── Pygame game loop ──────────────────────────────────────────────────────────

def run_pygame(world_state, spawn_x, spawn_y):
    from nemo.ui.renderer import Renderer
    KEY_ACTIONS = _make_pygame_keymap()

    renderer = Renderer()
    renderer.center_on(world_state.nemo.x, world_state.nemo.y)
    renderer.add_message("World initialized.")
    renderer.add_message(f"Nemo spawned at ({spawn_x}, {spawn_y}).")
    renderer.add_message("TAB: toggle control.  Q: quit.")

    clock = pygame.time.Clock()
    control_mode = "nemo"
    renderer.add_message("Control: NEMO")
    nemo_thinking = False
    nemo_result_holder = []
    nemo = world_state.nemo

    running = True
    while running:
        clock.tick(30)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    running = False
                elif event.key == pygame.K_TAB:
                    control_mode = "aaron" if control_mode == "nemo" else "nemo"
                    renderer.add_message(f"Control: {control_mode.upper()}")
                elif control_mode == "aaron" and event.key in KEY_ACTIONS:
                    action_name, args = KEY_ACTIONS[event.key]
                    result = apply_action(action_name, args, nemo, world_state, renderer)
                    if result.world_changed:
                        world_state.advance_tick()
                        renderer.center_on(nemo.x, nemo.y)

        if control_mode == "nemo" and not nemo_thinking:
            nemo_result_holder.clear()
            nemo_thinking = True
            t = threading.Thread(target=nemo_think_async,
                                 args=(world_state, nemo_result_holder), daemon=True)
            t.start()
            renderer.add_message("Nemo is thinking...")

        if nemo_thinking and nemo_result_holder:
            nemo_thinking = False
            _process_nemo_result(nemo_result_holder[0], nemo, world_state, renderer)
            pygame.time.wait(500)

        renderer.draw(world_state)

    pygame.quit()

# ── Curses game loop ──────────────────────────────────────────────────────────

def run_curses(stdscr, world_state, spawn_x, spawn_y):
    import curses
    import time
    from nemo.ui.curses_renderer import CursesRenderer

    CURSES_KEYS = {
        curses.KEY_UP:    ("move", {"direction": "north"}),
        curses.KEY_DOWN:  ("move", {"direction": "south"}),
        curses.KEY_LEFT:  ("move", {"direction": "west"}),
        curses.KEY_RIGHT: ("move", {"direction": "east"}),
        ord("w"): ("move", {"direction": "north"}),
        ord("s"): ("move", {"direction": "south"}),
        ord("a"): ("move", {"direction": "west"}),
        ord("d"): ("move", {"direction": "east"}),
        ord("k"): ("move", {"direction": "north"}),
        ord("j"): ("move", {"direction": "south"}),
        ord("h"): ("move", {"direction": "west"}),
        ord("l"): ("move", {"direction": "east"}),
        ord("p"): ("pickup", {}),
        ord("e"): ("examine", {"target": "surroundings"}),
        ord("."): ("wait", {}),
    }

    renderer = CursesRenderer(stdscr)
    renderer.center_on(world_state.nemo.x, world_state.nemo.y)
    renderer.add_message("World initialized.")
    renderer.add_message(f"Nemo at ({spawn_x},{spawn_y}). TAB:toggle Q:quit")

    control_mode = "nemo"
    nemo_thinking = False
    nemo_result_holder = []
    nemo = world_state.nemo

    running = True
    while running:
        key = renderer.get_input()

        if key == ord("q"):
            running = False
        elif key == ord("\t"):
            control_mode = "aaron" if control_mode == "nemo" else "nemo"
            renderer.add_message(f"Control: {control_mode.upper()}")
        elif control_mode == "aaron" and key in CURSES_KEYS:
            action_name, args = CURSES_KEYS[key]
            result = apply_action(action_name, args, nemo, world_state, renderer)
            if result.world_changed:
                world_state.advance_tick()
                renderer.center_on(nemo.x, nemo.y)

        if control_mode == "nemo" and not nemo_thinking:
            nemo_result_holder.clear()
            nemo_thinking = True
            t = threading.Thread(target=nemo_think_async,
                                 args=(world_state, nemo_result_holder), daemon=True)
            t.start()
            renderer.add_message("Nemo is thinking...")

        if nemo_thinking and nemo_result_holder:
            nemo_thinking = False
            _process_nemo_result(nemo_result_holder[0], nemo, world_state, renderer)
            time.sleep(0.5)

        renderer.draw(world_state)
        time.sleep(0.033)

# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    world_state, sx, sy = _init_world()
    if USE_CURSES:
        import curses
        print("[NEMO] Terminal mode (curses). Press Q to quit.")
        curses.wrapper(run_curses, world_state, sx, sy)
    else:
        print("[NEMO] Graphical mode (pygame).")
        run_pygame(world_state, sx, sy)
    print("[NEMO] Goodbye.")


if __name__ == "__main__":
    run()
