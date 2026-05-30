"""
main.py — Moriarty world engine entry point.

Controls (Aaron mode):
  Arrow keys / WASD / hjkl : move
  P: pickup   E: examine   . : wait   TAB: toggle control   Q: quit

Renderer auto-detected:
  - Display available (DISPLAY/WAYLAND_DISPLAY set, or macOS) -> pygame
  - No display (SSH without X) -> curses
  - Force curses: MORIARTY_RENDERER=curses python main.py
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

USE_CURSES = (not _has_display()) or os.environ.get("MORIARTY_RENDERER") == "curses"

# Only import pygame when we actually need it
if not USE_CURSES:
    import pygame

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nemo.world.mapgen import generate_world, find_spawn
from nemo.world.state import WorldState
from nemo.entities.base import MoriartyEntity, EntityType
from nemo.entities.items import make_apple, make_stick
from nemo.entities.actions import resolve_action, ActionResult
from nemo.brain import moriarty_brain
from nemo.memory import wiki

log = logging.getLogger("moriarty")

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

# Tick speed presets: seconds of post-tick delay (0 = as fast as Ollama allows)
TICK_DELAYS = [0, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]
TICK_DELAY_DEFAULT = 3  # index into TICK_DELAYS — starts at 1.0s

# ── Shared helpers ────────────────────────────────────────────────────────────

def moriarty_think_async(world_state, result_holder, reasoning=False):
    """Run Moriarty's brain in a background thread so the UI stays responsive."""
    perception = world_state.build_perception_block()
    action_dict = moriarty_brain.think(perception, reasoning=reasoning)
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


def _handle_reflection(moriarty, world_state, renderer):
    renderer.add_message("[Moriarty is reflecting...]")
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
        {"role": "system", "content": "You are Moriarty. Reflect honestly."},
        {"role": "user",   "content": prompt},
    ]
    response = moriarty_brain.call_ollama(messages, thinking=True, timeout=60)
    if response:
        wiki.update_self_model(response)
        renderer.add_message("[Self-model updated.]")
        moriarty.log_event("Reflected and updated self-model.")


def _process_moriarty_result(action_dict, moriarty, world_state, renderer):
    """Handle one brain tick result: log thought, execute action, record event."""
    if action_dict["thought"]:
        renderer.last_thought = action_dict["thought"]
        moriarty.log_event(f"[THOUGHT] {action_dict['thought']}")

    log.info(f"LOOP tick={world_state.tick} action={action_dict['action']} args={action_dict['args']}")

    if action_dict["memory_tool"]:
        mem_result = wiki.execute_memory_tool(action_dict["memory_tool"])
        world_state.pending_memory_result = mem_result
        renderer.add_message(f"[MEM] {mem_result[:80]}")

    result = apply_action(action_dict["action"], action_dict["args"],
                          moriarty, world_state, renderer)
    if result.world_changed:
        world_state.advance_tick()
        renderer.center_on(moriarty.x, moriarty.y)


def _init_world():
    """Build the world, spawn Moriarty, scatter starting items."""
    print("[MORIARTY] Generating world...")
    world = generate_world(width=512, height=512, seed=42)
    spawn_x, spawn_y = find_spawn(world)

    moriarty = MoriartyEntity(name="Moriarty", entity_type=EntityType.MORIARTY,
                      x=spawn_x, y=spawn_y)
    world_state = WorldState(world=world, moriarty=moriarty)

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
    moriarty.status.hunger = 80

    wiki._ensure_dirs()
    wiki.get_self_model()

    return world_state, spawn_x, spawn_y

# ── Pygame game loop ──────────────────────────────────────────────────────────

def run_pygame(world_state, spawn_x, spawn_y):
    from nemo.ui.renderer import Renderer
    KEY_ACTIONS = _make_pygame_keymap()

    renderer = Renderer()
    renderer.center_on(world_state.moriarty.x, world_state.moriarty.y)
    renderer.add_message("World initialized.")
    renderer.add_message(f"Moriarty spawned at ({spawn_x}, {spawn_y}).")
    renderer.add_message("TAB: toggle control.  Q: quit.")

    clock = pygame.time.Clock()
    control_mode = "moriarty"
    tick_delay_idx = TICK_DELAY_DEFAULT
    stepped = False
    step_requested = False
    reasoning = False
    renderer.tick_delay_idx = tick_delay_idx
    renderer.tick_delay = TICK_DELAYS[tick_delay_idx]
    renderer.stepped = stepped
    renderer.add_message("Control: MORIARTY  ?:help")
    moriarty_thinking = False
    moriarty_result_holder = []
    moriarty = world_state.moriarty

    running = True
    while running:
        clock.tick(30)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if renderer.show_help:
                    renderer.show_help = False
                    continue
                if event.key == pygame.K_q:
                    running = False
                elif event.key == pygame.K_TAB:
                    control_mode = "aaron" if control_mode == "moriarty" else "moriarty"
                    renderer.add_message(f"Control: {control_mode.upper()}")
                elif event.key == pygame.K_LEFTBRACKET:
                    tick_delay_idx = max(0, tick_delay_idx - 1)
                    renderer.tick_delay_idx = tick_delay_idx
                    renderer.tick_delay = TICK_DELAYS[tick_delay_idx]
                    renderer.add_message(f"Speed: {TICK_DELAYS[tick_delay_idx]}s")
                elif event.key == pygame.K_RIGHTBRACKET:
                    tick_delay_idx = min(len(TICK_DELAYS) - 1, tick_delay_idx + 1)
                    renderer.tick_delay_idx = tick_delay_idx
                    renderer.tick_delay = TICK_DELAYS[tick_delay_idx]
                    renderer.add_message(f"Speed: {TICK_DELAYS[tick_delay_idx]}s")
                elif event.key == pygame.K_v:
                    renderer.show_los = not renderer.show_los
                    renderer.add_message("LOS overlay ON" if renderer.show_los else "LOS overlay OFF")
                elif event.key == pygame.K_r:
                    reasoning = not reasoning
                    renderer.add_message(f"Reasoning: {'ON (slower)' if reasoning else 'OFF'}")
                elif event.key in (pygame.K_SLASH, pygame.K_QUESTION):
                    renderer.show_help = not renderer.show_help
                elif event.key == pygame.K_SPACE:
                    stepped = not stepped
                    renderer.stepped = stepped
                    renderer.add_message("STEP mode ON — press . to advance" if stepped else "STEP mode OFF")
                elif event.key == pygame.K_PERIOD and control_mode == "moriarty" and stepped:
                    step_requested = True
                elif control_mode == "aaron" and event.key in KEY_ACTIONS:
                    action_name, args = KEY_ACTIONS[event.key]
                    result = apply_action(action_name, args, moriarty, world_state, renderer)
                    if result.world_changed:
                        world_state.advance_tick()
                        renderer.center_on(moriarty.x, moriarty.y)

        if control_mode == "moriarty" and not moriarty_thinking:
            if not stepped or step_requested:
                step_requested = False
                moriarty_result_holder.clear()
                moriarty_thinking = True
                t = threading.Thread(target=moriarty_think_async,
                                     args=(world_state, moriarty_result_holder, reasoning), daemon=True)
                t.start()

        if moriarty_thinking and moriarty_result_holder:
            moriarty_thinking = False
            _process_moriarty_result(moriarty_result_holder[0], moriarty, world_state, renderer)
            delay_ms = int(TICK_DELAYS[tick_delay_idx] * 1000)
            if delay_ms > 0 and not stepped:
                pygame.time.wait(delay_ms)

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
    renderer.center_on(world_state.moriarty.x, world_state.moriarty.y)
    renderer.add_message("World initialized.")
    renderer.add_message(f"Moriarty at ({spawn_x},{spawn_y}). TAB:toggle Q:quit")

    control_mode = "moriarty"
    tick_delay_idx = TICK_DELAY_DEFAULT
    stepped = False
    step_requested = False
    reasoning = False
    renderer.tick_delay_idx = tick_delay_idx
    renderer.tick_delay = TICK_DELAYS[tick_delay_idx]
    renderer.stepped = stepped
    renderer.add_message("Control: MORIARTY  ?:help")
    moriarty_thinking = False
    moriarty_result_holder = []
    moriarty = world_state.moriarty

    running = True
    while running:
        key = renderer.get_input()

        if renderer.show_help and key != -1:
            renderer.show_help = False
            continue
        if key == ord("q"):
            running = False
        elif key == ord("\t"):
            control_mode = "aaron" if control_mode == "moriarty" else "moriarty"
            renderer.add_message(f"Control: {control_mode.upper()}")
        elif key == ord("["):
            tick_delay_idx = max(0, tick_delay_idx - 1)
            renderer.tick_delay_idx = tick_delay_idx
            renderer.tick_delay = TICK_DELAYS[tick_delay_idx]
            renderer.add_message(f"Speed: {TICK_DELAYS[tick_delay_idx]}s")
        elif key == ord("]"):
            tick_delay_idx = min(len(TICK_DELAYS) - 1, tick_delay_idx + 1)
            renderer.tick_delay_idx = tick_delay_idx
            renderer.tick_delay = TICK_DELAYS[tick_delay_idx]
            renderer.add_message(f"Speed: {TICK_DELAYS[tick_delay_idx]}s")
        elif key == ord("v"):
            renderer.show_los = not renderer.show_los
            renderer.add_message("LOS overlay ON" if renderer.show_los else "LOS overlay OFF")
        elif key == ord("r"):
            reasoning = not reasoning
            renderer.add_message(f"Reasoning: {'ON (slower)' if reasoning else 'OFF'}")
        elif key == ord("?"):
            renderer.show_help = not renderer.show_help
        elif key == ord(" "):
            stepped = not stepped
            renderer.stepped = stepped
            renderer.add_message("STEP mode ON — press . to advance" if stepped else "STEP mode OFF")
        elif key == ord(".") and control_mode == "moriarty" and stepped:
            step_requested = True
        elif control_mode == "aaron" and key in CURSES_KEYS:
            action_name, args = CURSES_KEYS[key]
            result = apply_action(action_name, args, moriarty, world_state, renderer)
            if result.world_changed:
                world_state.advance_tick()
                renderer.center_on(moriarty.x, moriarty.y)

        if control_mode == "moriarty" and not moriarty_thinking:
            if not stepped or step_requested:
                step_requested = False
                moriarty_result_holder.clear()
                moriarty_thinking = True
                t = threading.Thread(target=moriarty_think_async,
                                     args=(world_state, moriarty_result_holder, reasoning), daemon=True)
                t.start()

        if moriarty_thinking and moriarty_result_holder:
            moriarty_thinking = False
            _process_moriarty_result(moriarty_result_holder[0], moriarty, world_state, renderer)
            if not stepped:
                time.sleep(TICK_DELAYS[tick_delay_idx])

        renderer.draw(world_state)
        time.sleep(0.033)

# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    world_state, sx, sy = _init_world()
    if USE_CURSES:
        import curses
        print("[MORIARTY] Terminal mode (curses). Press Q to quit.")
        curses.wrapper(run_curses, world_state, sx, sy)
    else:
        print("[MORIARTY] Graphical mode (pygame).")
        run_pygame(world_state, sx, sy)
    print("[MORIARTY] Goodbye.")


if __name__ == "__main__":
    run()
