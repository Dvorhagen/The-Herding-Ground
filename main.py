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
import time as _time

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

from moriarty.world.tiles import WorldMap
from moriarty.world.mapgen import find_spawn, populate_natural_objects, populate_animals
from moriarty.world.state import WorldState
from moriarty.world.save import save_world, load_world, save_info, IncompatibleSaveError
from moriarty.entities.base import MoriartyEntity, PlayerEntity, EntityType, DIRECTIONS
from moriarty.entities.items import (make_apple, make_stick,
    make_worn_tunic, make_rough_trousers, make_simple_boots, make_small_satchel)
from moriarty.world.objects import make_campfire, make_chest
from moriarty.entities.actions import resolve_action, ActionResult
from moriarty.brain import moriarty_brain
from moriarty.brain.moriarty_brain import PROMPT_STYLES, PROMPT_LABELS
from moriarty.memory import wiki
from moriarty import config as _config
from moriarty.ui.startup_menu import show as _show_menu

log = logging.getLogger("moriarty")

# ── Pygame key map (only used when pygame is active) ─────────────────────────
def _make_pygame_keymap():
    return {
        # Arrow keys
        pygame.K_UP:     ("move", {"direction": "north"}),
        pygame.K_DOWN:   ("move", {"direction": "south"}),
        pygame.K_LEFT:   ("move", {"direction": "west"}),
        pygame.K_RIGHT:  ("move", {"direction": "east"}),
        # WASD
        pygame.K_w:      ("move", {"direction": "north"}),
        pygame.K_s:      ("move", {"direction": "south"}),
        pygame.K_a:      ("move", {"direction": "west"}),
        pygame.K_d:      ("move", {"direction": "east"}),
        # hjkl + diagonal vi-keys
        pygame.K_k:      ("move", {"direction": "north"}),
        pygame.K_j:      ("move", {"direction": "south"}),
        pygame.K_h:      ("move", {"direction": "west"}),
        pygame.K_l:      ("move", {"direction": "east"}),
        pygame.K_y:      ("move", {"direction": "nw"}),
        pygame.K_u:      ("move", {"direction": "ne"}),
        pygame.K_b:      ("move", {"direction": "sw"}),
        pygame.K_n:      ("move", {"direction": "se"}),
        # Numpad (all 8 directions + 5=wait)
        pygame.K_KP8:    ("move", {"direction": "north"}),
        pygame.K_KP2:    ("move", {"direction": "south"}),
        pygame.K_KP4:    ("move", {"direction": "west"}),
        pygame.K_KP6:    ("move", {"direction": "east"}),
        pygame.K_KP7:    ("move", {"direction": "nw"}),
        pygame.K_KP9:    ("move", {"direction": "ne"}),
        pygame.K_KP1:    ("move", {"direction": "sw"}),
        pygame.K_KP3:    ("move", {"direction": "se"}),
        pygame.K_KP5:    ("wait", {}),
        # Actions
        pygame.K_p:      ("pickup", {}),
        pygame.K_e:      ("examine", {"target": "surroundings"}),
        pygame.K_PERIOD: ("wait", {}),
    }

# Tick speed presets: seconds of post-tick delay (0 = as fast as Ollama allows)
TICK_DELAYS = [0, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]
TICK_DELAY_DEFAULT = 3  # index into TICK_DELAYS — starts at 1.0s

# ── Shared helpers ────────────────────────────────────────────────────────────

def moriarty_think_async(perception: str, result_holder, style="structured"):
    """
    Run Moriarty's brain in a background thread.
    Receives a pre-built perception snapshot so the brain thread never touches
    world state — eliminates threading races with the main loop.
    """
    action_dict = moriarty_brain.think(perception, style=style)
    result_holder.append(action_dict)


def apply_action(action_name, args, actor, world_state, renderer):
    """Execute one action and push the result message to the renderer."""
    result = resolve_action(action_name, args, actor, world_state)
    renderer.add_message(result.message)
    if not (result.data and result.data.get("no_log")):
        actor.log_event(result.message)
    log.info(f"GAME action={action_name} args={args} ok={result.success} | {result.message[:80]}")
    if result.data and result.data.get("trigger_reflection"):
        _handle_reflection(actor, world_state, renderer)
    if result.data and result.data.get("trigger_sleep"):
        renderer.add_message("[Moriarty sleeps... dreams stir]")
    if result.data and result.data.get("speech") and hasattr(renderer, "add_speech_bubble"):
        renderer.add_speech_bubble(actor.name, result.data["speech"])
    return result


def _handle_reflection(moriarty, world_state, renderer):
    renderer.add_message("[Moriarty is reflecting...]")
    renderer.reasoning_stream = ""
    _buf = []
    _last = [0.0]
    def _on_thinking(chunk):
        _buf.append(chunk)
        now = _time.monotonic()
        if now - _last[0] >= 0.4:
            renderer.reasoning_stream = "".join(_buf)[-600:]
            _last[0] = now

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
    response = moriarty_brain.call_ollama(messages, thinking=True, on_thinking=_on_thinking)
    renderer.reasoning_stream = ""
    if response:
        wiki.update_self_model(response)
        renderer.add_message("[Self-model updated.]")
        moriarty.log_event("Reflected and updated self-model.")


def _process_moriarty_result(action_dict, moriarty, world_state, renderer,
                             follow_mo=True, prompt_label=""):
    """Handle one brain tick result: log thought, execute action, record event."""
    if action_dict["thought"]:
        renderer.last_thought = action_dict["thought"]
        moriarty.log_event(f"[THOUGHT] {action_dict['thought']}")

    log.info(f"LOOP tick={world_state.tick} action={action_dict['action']} args={action_dict['args']}")

    if action_dict["memory_tool"]:
        tool = action_dict["memory_tool"]
        # Inject the current prompt style tag into write calls so Aaron can
        # see which style produced which memory entries (stripped on read-back).
        if tool.get("tool") == "write" and prompt_label:
            tool = dict(tool, _style_tag=prompt_label)
        mem_result = wiki.execute_memory_tool(tool)
        world_state.pending_memory_result = mem_result
        renderer.add_message(f"[MEM] {mem_result[:80]}")

    result = apply_action(action_dict["action"], action_dict["args"],
                          moriarty, world_state, renderer)
    if result.world_changed:
        world_state.advance_tick()
        if follow_mo:
            renderer.center_on(moriarty.x, moriarty.y)


def _process_text_input_key(key, renderer, control_mode, player_entity, moriarty, world_state):
    """
    Handle one keypress while the non-blocking text input bar is open.
    Called from the main loop every frame when renderer.text_input_active is True.
    No blocking curses calls — just appends to renderer.text_input_buffer.
    """
    import curses as _c
    if key in (10, 13, _c.KEY_ENTER):           # Enter — submit
        text = "".join(renderer.text_input_buffer).strip()
        renderer.text_input_active = False
        renderer.text_input_buffer = []
        if not text:
            return
        if renderer.text_input_mode == "god_inject":
            world_state.injected_environment = text
            renderer.add_message(f"[ENV] {text[:70]}")
        elif renderer.text_input_mode == "player_talk" and player_entity:
            world_state.pending_messages.append({
                "from_name": player_entity.name,
                "to_id":     moriarty.id,
                "message":   text,
                "tick":      world_state.tick,
            })
            if hasattr(renderer, "add_speech_bubble"):
                renderer.add_speech_bubble(player_entity.name, text)
            renderer.add_message(f'[you → Mo]: "{text}"')
        elif renderer.text_input_mode == "player_command" and player_entity:
            _player_command(text, player_entity, world_state, renderer)
    elif key == 27:                              # ESC — cancel
        renderer.text_input_active = False
        renderer.text_input_buffer = []
        renderer.add_message("(cancelled)")
    elif key in (8, 127, _c.KEY_BACKSPACE):      # Backspace
        if renderer.text_input_buffer:
            renderer.text_input_buffer.pop()
    elif 32 <= key < 127:                        # Printable ASCII
        renderer.text_input_buffer.append(chr(key))


def _find_player_spawn(world_state) -> tuple:
    """Find a passable, unoccupied tile near Mo for the player avatar."""
    mo = world_state.moriarty
    for radius in range(2, 12):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if abs(dx) != radius and abs(dy) != radius:
                    continue  # only the shell of this radius
                x, y = mo.x + dx, mo.y + dy
                if (world_state.world.is_passable(x, y)
                        and not world_state.get_entities_at(x, y)
                        and not world_state.get_objects_at(x, y)):
                    return x, y
    return mo.x + 3, mo.y  # fallback


def _player_action(action_name: str, args: dict, player, world_state, renderer):
    """Execute an action on behalf of the player avatar and show the result."""
    result = resolve_action(action_name, args, player, world_state)
    renderer.add_message(f"[you] {result.message}")


def _player_command(text: str, player, world_state, renderer):
    """Parse a free-text command from the player using the NATURAL parser."""
    from moriarty.brain.moriarty_brain import parse_natural_response
    # Wrap as a two-line natural response (blank thought + command line)
    parsed = parse_natural_response(f"(command)\n{text.strip()}")
    result = resolve_action(parsed["action"], parsed["args"], player, world_state)
    renderer.add_message(f"[you] {result.message}")


def _player_hotkey(key, player, world_state, renderer):
    """Handle player-mode action hotkeys not in KEY_ACTIONS."""
    # These are only checked in pygame mode
    if not hasattr(renderer, 'text_input_active'):
        return

    import pygame

    if key == pygame.K_d:           # Drop last inventory item
        if player.inventory:
            item = player.inventory[-1]
            result = resolve_action("drop", {"item_name": item.name}, player, world_state)
            renderer.add_message(f"[you] {result.message}")
        else:
            renderer.add_message("[you] Nothing to drop.")

    elif key == pygame.K_u:         # Use best consumable
        usable = [i for i in player.inventory if getattr(i, 'usable', False)]
        if usable:
            result = resolve_action("use", {"item_name": usable[0].name}, player, world_state)
            renderer.add_message(f"[you] {result.message}")
        else:
            renderer.add_message("[you] Nothing usable in inventory.")

    elif key == pygame.K_e:         # Examine surroundings
        result = resolve_action("examine", {"target": "surroundings"}, player, world_state)
        renderer.add_message(f"[you] {result.message[:120]}")

    elif key in (pygame.K_f, pygame.K_a):   # Attack nearest animal
        result = resolve_action("attack", {}, player, world_state)
        renderer.add_message(f"[you] {result.message}")

    elif key == pygame.K_g:         # Grapple
        result = resolve_action("grapple", {}, player, world_state)
        renderer.add_message(f"[you] {result.message}")

    elif key == pygame.K_w:         # Equip best weapon
        weapons = [i for i in player.inventory if getattr(i, 'slot', '') == 'weapon']
        if weapons:
            best = max(weapons, key=lambda i: getattr(i, 'damage', 0))
            result = resolve_action("equip", {"item_name": best.name}, player, world_state)
            renderer.add_message(f"[you] {result.message}")
        else:
            renderer.add_message("[you] No weapon in inventory.")

    elif key == pygame.K_c:         # Craft menu
        from moriarty.entities.crafting import RECIPES, can_craft
        lines = []
        craftable = []
        for i, (name, recipe) in enumerate(RECIPES.items(), 1):
            ok, _ = can_craft(player.inventory, recipe)
            mark = "✓" if ok else "✗"
            lines.append(f"  {mark} {i}. {name}")
            if ok:
                craftable.append((i, name))
        renderer.add_message("Recipes: " + " | ".join(lines))

    elif key == pygame.K_SLASH:     # Free command input
        renderer.text_input_active = True
        renderer.text_input_prompt = "Command"
        renderer.text_input_mode   = "player_command"
        renderer.text_input_buffer = []


def _player_move(player_entity, direction: str, world_state, renderer) -> bool:
    """Move the player avatar one step. Returns True if moved."""
    if direction not in DIRECTIONS:
        return False
    dx, dy = DIRECTIONS[direction]
    nx, ny = player_entity.x + dx, player_entity.y + dy
    for obj in world_state.get_objects_at(nx, ny):
        if getattr(obj, 'blocks', False):
            renderer.add_message(f"The {obj.name} blocks your way.")
            return False
    if world_state.world.is_passable(nx, ny):
        player_entity.x = nx
        player_entity.y = ny
        return True
    renderer.add_message("Can't go that way.")
    return False


def _init_world(seed: int = 42):
    """Build the world, spawn Moriarty, scatter starting items."""
    print("[MORIARTY] Generating world...")
    world = WorldMap(seed=seed)
    spawn_x, spawn_y = find_spawn(world)

    moriarty = MoriartyEntity(name="Moriarty", entity_type=EntityType.MORIARTY,
                      x=spawn_x, y=spawn_y)
    world_state = WorldState(world=world, moriarty=moriarty)

    def near_spawn(dx, dy):
        """Find a passable tile near spawn + offset."""
        bx, by = spawn_x + dx, spawn_y + dy
        for ox, oy in ((0,0),(1,0),(-1,0),(0,1),(0,-1)):
            if world.is_passable(bx + ox, by + oy):
                return bx + ox, by + oy
        return bx, by

    ax, ay = near_spawn( 1,  0); world_state.add_entity(make_apple(ax, ay))
    ax, ay = near_spawn( 2,  1); world_state.add_entity(make_apple(ax, ay))
    ax, ay = near_spawn(-1,  2); world_state.add_entity(make_apple(ax, ay))
    sx, sy = near_spawn( 1, -1); world_state.add_entity(make_stick(sx, sy))
    moriarty.status.hunger = 80

    # Dress Mo — he starts clothed, not naked
    for item in (make_worn_tunic(), make_rough_trousers(),
                 make_simple_boots(), make_small_satchel()):
        moriarty.equip(item)

    # Starter objects near spawn
    cx, cy = near_spawn(3,  0)
    world_state.add_object(make_campfire(cx, cy))
    cx, cy = near_spawn(-2, 1)
    world_state.add_object(make_chest(cx, cy, contents=[make_apple(cx, cy)]))

    # Populate the natural world around spawn
    print("[MORIARTY] Populating natural objects...")
    populate_natural_objects(world_state, seed=seed, cx=spawn_x, cy=spawn_y)
    print("[MORIARTY] Populating animals...")
    populate_animals(world_state, seed=seed, cx=spawn_x, cy=spawn_y)

    wiki._ensure_dirs()
    wiki.get_self_model()

    return world_state, spawn_x, spawn_y

# ── Pygame game loop ──────────────────────────────────────────────────────────

def run_pygame(world_state, spawn_x, spawn_y, cfg=None):
    from moriarty.ui.renderer import Renderer
    KEY_ACTIONS = _make_pygame_keymap()

    renderer = Renderer()
    renderer.center_on(world_state.moriarty.x, world_state.moriarty.y)
    renderer.add_message("World initialized.")
    renderer.add_message(f"Moriarty spawned at ({spawn_x}, {spawn_y}).")
    renderer.add_message("TAB: toggle control.  Q: quit.")

    clock = pygame.time.Clock()
    # control_mode: "moriarty" | "awaiting_mode_choice" | "god" | "player"
    control_mode = "moriarty"
    player_entity = None
    cfg = cfg or {}
    tick_delay_idx = cfg.get("tick_delay_idx", TICK_DELAY_DEFAULT)
    stepped        = cfg.get("default_stepped", False)
    step_requested = False
    prompt_style_idx = 0
    renderer.tick_delay_idx = tick_delay_idx
    renderer.tick_delay = TICK_DELAYS[tick_delay_idx]
    renderer.stepped = stepped
    renderer.add_message(f"MORIARTY mode — TAB:drop-in  ?:help  Prompt:{PROMPT_LABELS[prompt_style_idx]}")
    moriarty_thinking = False
    moriarty_result_holder = []
    moriarty = world_state.moriarty
    mo_idle_until = 0.0

    GOD_PAN = {
        pygame.K_UP:    (0, -3), pygame.K_DOWN:  (0,  3),
        pygame.K_LEFT:  (-3, 0), pygame.K_RIGHT: (3,  0),
        pygame.K_k:     (0, -3), pygame.K_j:     (0,  3),
        pygame.K_h:     (-3, 0), pygame.K_l:     (3,  0),
    }

    running = True
    while running:
        clock.tick(30)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:

                # ── Text input: intercepts ALL keys while active ──────────────
                if renderer.text_input_active:
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        text = "".join(renderer.text_input_buffer).strip()
                        renderer.text_input_active = False
                        renderer.text_input_buffer = []
                        if text:
                            if renderer.text_input_mode == "god_inject":
                                world_state.injected_environment = text
                                renderer.add_message(f"[ENV] {text[:70]}")
                            elif renderer.text_input_mode == "player_talk" and player_entity:
                                world_state.pending_messages.append({
                                    "from_name": player_entity.name,
                                    "to_id":     moriarty.id,
                                    "message":   text,
                                    "tick":      world_state.tick,
                                })
                                renderer.add_speech_bubble(player_entity.name, text)
                                renderer.add_message(f'[you → Mo]: "{text}"')
                    elif event.key == pygame.K_ESCAPE:
                        renderer.text_input_active = False
                        renderer.text_input_buffer = []
                        renderer.add_message("(cancelled)")
                    elif event.key == pygame.K_BACKSPACE:
                        if renderer.text_input_buffer:
                            renderer.text_input_buffer.pop()
                    elif event.unicode and 32 <= ord(event.unicode) < 127:
                        renderer.text_input_buffer.append(event.unicode)
                    continue  # skip all game-control handling while typing

                # ── Help overlay ──────────────────────────────────────────────
                if renderer.show_help:
                    renderer.show_help = False
                    continue

                # ── Global keys ───────────────────────────────────────────────
                if event.key == pygame.K_q:
                    running = False
                elif event.key == pygame.K_TAB:
                    if control_mode == "moriarty":
                        control_mode = "awaiting_mode_choice"
                        renderer.control_mode_label = "DROP-IN?"
                        renderer.add_message("Drop in as:  G = god observer   P = player   ESC = cancel")
                    else:
                        if control_mode == "player" and player_entity:
                            renderer.add_message("You step back. Your figure stays.")
                        elif control_mode == "god":
                            renderer.add_message("Back to observation.")
                        control_mode = "moriarty"
                        renderer.control_mode_label = "MORIARTY"
                        renderer.player_entity = None
                        renderer.center_on(moriarty.x, moriarty.y)

                # ── T: open text input (non-blocking) ─────────────────────────
                elif event.key == pygame.K_t:
                    if control_mode == "god":
                        renderer.text_input_active = True
                        renderer.text_input_prompt = "Inject [ENVIRONMENT]"
                        renderer.text_input_mode = "god_inject"
                        renderer.text_input_buffer = []
                    elif control_mode == "player" and player_entity:
                        renderer.text_input_active = True
                        renderer.text_input_prompt = f"Say (as {player_entity.name})"
                        renderer.text_input_mode = "player_talk"
                        renderer.text_input_buffer = []
                    elif control_mode == "awaiting_mode_choice":
                        renderer.add_message("Choose G or P first, then t.")
                    else:
                        renderer.add_message("TAB → P (player) or G (god) first, then t.")

                # ── Drop-in mode selection ────────────────────────────────────
                elif control_mode == "awaiting_mode_choice":
                    if event.key == pygame.K_g:
                        control_mode = "god"
                        renderer.control_mode_label = "GOD"
                        renderer.add_message("GOD MODE — arrows:pan  m:jump to Mo  t:inject")
                    elif event.key == pygame.K_p:
                        if player_entity is None:
                            px, py = _find_player_spawn(world_state)
                            player_entity = PlayerEntity(name="figure", x=px, y=py)
                            world_state.add_entity(player_entity)
                            world_state.pending_messages.append({
                                "from_name": "world", "to_id": "broadcast",
                                "message": "A figure appears nearby.", "tick": world_state.tick,
                            })
                            renderer.add_message(f"You appear at ({px},{py}) as a figure.")
                        control_mode = "player"
                        renderer.control_mode_label = "PLAYER"
                        renderer.player_entity = player_entity
                        renderer.center_on(player_entity.x, player_entity.y)
                        renderer.add_message("PLAYER — arrows:move  t:talk  f:attack  w:equip  /:command")
                    elif event.key == pygame.K_ESCAPE:
                        control_mode = "moriarty"
                        renderer.control_mode_label = "MORIARTY"
                        renderer.add_message("Drop-in cancelled.")

                elif event.key == pygame.K_LEFTBRACKET:
                    tick_delay_idx = max(0, tick_delay_idx - 1)
                    renderer.tick_delay_idx = tick_delay_idx
                    renderer.tick_delay = TICK_DELAYS[tick_delay_idx]
                    renderer.add_message(f"Mo lag: {TICK_DELAYS[tick_delay_idx]}s")
                elif event.key == pygame.K_RIGHTBRACKET:
                    tick_delay_idx = min(len(TICK_DELAYS) - 1, tick_delay_idx + 1)
                    renderer.tick_delay_idx = tick_delay_idx
                    renderer.tick_delay = TICK_DELAYS[tick_delay_idx]
                    renderer.add_message(f"Mo lag: {TICK_DELAYS[tick_delay_idx]}s")
                elif event.key == pygame.K_v:
                    renderer.show_los = not renderer.show_los
                    renderer.add_message("LOS overlay ON" if renderer.show_los else "LOS overlay OFF")
                elif event.key == pygame.K_BACKQUOTE:
                    prompt_style_idx = (prompt_style_idx + 1) % len(PROMPT_STYLES)
                    renderer.add_message(f"Prompt: {PROMPT_LABELS[prompt_style_idx]}")
                elif event.key in (pygame.K_SLASH, pygame.K_QUESTION):
                    renderer.show_help = not renderer.show_help
                elif event.key == pygame.K_SPACE:
                    stepped = not stepped
                    renderer.stepped = stepped
                    renderer.add_message("STEP mode ON — press . to advance" if stepped else "STEP mode OFF")
                elif event.key == pygame.K_PERIOD and stepped:
                    step_requested = True
                elif event.key == pygame.K_m and control_mode == "god":
                    renderer.center_on(moriarty.x, moriarty.y)
                    renderer.add_message("Jumped to Moriarty.")

                # ── God mode: camera pan ──────────────────────────────────────
                elif control_mode == "god" and event.key in GOD_PAN:
                    ddx, ddy = GOD_PAN[event.key]
                    _extent = 500_000
                    renderer.view_x = max(-_extent, min(_extent, renderer.view_x + ddx))
                    renderer.view_y = max(-_extent, min(_extent, renderer.view_y + ddy))

                # ── Player mode: movement and actions ─────────────────────────
                elif control_mode == "player" and player_entity:
                    if event.key in KEY_ACTIONS:
                        action_name, args = KEY_ACTIONS[event.key]
                        if action_name == "move":
                            moved = _player_move(player_entity, args["direction"], world_state, renderer)
                            if moved:
                                renderer.center_on(player_entity.x, player_entity.y)
                                world_state.advance_tick()
                        else:
                            _player_action(action_name, args,
                                           player_entity, world_state, renderer)
                            world_state.advance_tick()
                    else:
                        _player_hotkey(event.key, player_entity, world_state, renderer)

        # Mo always thinks autonomously, gated by mo_idle_until
        import time as _t
        now = _t.monotonic()
        if not moriarty_thinking and now >= mo_idle_until:
            if not stepped or step_requested:
                step_requested = False
                moriarty_result_holder.clear()
                moriarty_thinking = True
                _perception = world_state.build_perception_block()
                _th = threading.Thread(target=moriarty_think_async,
                                       args=(_perception, moriarty_result_holder,
                                             PROMPT_STYLES[prompt_style_idx]), daemon=True)
                _th.start()

        if moriarty_thinking and moriarty_result_holder:
            moriarty_thinking = False
            _process_moriarty_result(
                moriarty_result_holder[0], moriarty, world_state, renderer,
                follow_mo=(control_mode == "moriarty"),
                prompt_label=PROMPT_LABELS[prompt_style_idx],
            )
            if player_entity:
                world_state.pending_messages = [
                    m for m in world_state.pending_messages
                    if m["to_id"] != player_entity.id
                ]
            if not stepped:
                mo_idle_until = _t.monotonic() + TICK_DELAYS[tick_delay_idx]

        renderer.draw(world_state)

    save_world(world_state, _config.SAVE_FILE)
    pygame.quit()

# ── Curses game loop ──────────────────────────────────────────────────────────

def run_curses(stdscr, world_state, spawn_x, spawn_y, cfg=None):
    import curses
    import time
    import signal
    from moriarty.ui.curses_renderer import CursesRenderer

    # ── SIGWINCH (terminal resize) safety ─────────────────────────────────────
    # Intercept the resize signal in Python and set a flag instead of letting
    # it reach ncurses's internal C handler mid-draw (which causes segfaults
    # on Termius/iOS when the keyboard appears or the device is rotated).
    # The flag is checked at the TOP of each frame, between draw calls.
    _resize_pending = [False]
    def _on_sigwinch(signum, frame):
        _resize_pending[0] = True
    try:
        _old_sigwinch = signal.signal(signal.SIGWINCH, _on_sigwinch)
    except (AttributeError, OSError):
        _old_sigwinch = None   # SIGWINCH not available on this platform

    MOVE_KEYS = {
        curses.KEY_UP:    "north",
        curses.KEY_DOWN:  "south",
        curses.KEY_LEFT:  "west",
        curses.KEY_RIGHT: "east",
        ord("w"): "north", ord("k"): "north",
        ord("s"): "south", ord("j"): "south",
        ord("a"): "west",  ord("h"): "west",
        ord("d"): "east",  ord("l"): "east",
        ord("y"): "nw",    ord("u"): "ne",
        ord("b"): "sw",    ord("n"): "se",
        # Numpad with numlock ON (sends digit chars)
        ord("8"): "north", ord("2"): "south",
        ord("4"): "west",  ord("6"): "east",
        ord("7"): "nw",    ord("9"): "ne",
        ord("1"): "sw",    ord("3"): "se",
        # Numpad with numlock OFF (curses KEY_* constants)
        curses.KEY_A1: "nw",    curses.KEY_A3: "ne",
        curses.KEY_C1: "sw",    curses.KEY_C3: "se",
        curses.KEY_B2: "wait",  # centre key = wait
    }

    renderer = CursesRenderer(stdscr)
    renderer.center_on(world_state.moriarty.x, world_state.moriarty.y)
    renderer.add_message("World initialized.")
    renderer.add_message(f"Moriarty at ({spawn_x},{spawn_y}).")
    renderer.add_message("TAB: drop in as god or player.  ?: help  q: quit")

    # control_mode: "moriarty" | "awaiting_mode_choice" | "god" | "player"
    control_mode = "moriarty"
    player_entity = None

    cfg = cfg or {}
    tick_delay_idx = cfg.get("tick_delay_idx", TICK_DELAY_DEFAULT)
    stepped        = cfg.get("default_stepped", False)
    step_requested = False
    prompt_style_idx = 0
    renderer.tick_delay_idx = tick_delay_idx
    renderer.tick_delay = TICK_DELAYS[tick_delay_idx]
    renderer.stepped = stepped
    renderer.control_mode_label = "MORIARTY"
    renderer.add_message(f"Prompt: {PROMPT_LABELS[prompt_style_idx]}")

    moriarty_thinking = False
    moriarty_result_holder = []
    moriarty = world_state.moriarty
    mo_idle_until = 0.0   # timestamp: don't start next think cycle until this time

    running = True
    while running:
      try:
        # ── Handle terminal resize between frames (never mid-draw) ────────────
        if _resize_pending[0]:
            _resize_pending[0] = False
            try:
                curses.update_lines_cols()
                stdscr.clear()
                renderer.center_on(moriarty.x, moriarty.y)
            except curses.error:
                pass

        key = renderer.get_input()

        # Also handle KEY_RESIZE events sent by the terminal itself
        if key == curses.KEY_RESIZE:
            try:
                curses.update_lines_cols()
                stdscr.clear()
                renderer.center_on(moriarty.x, moriarty.y)
            except curses.error:
                pass
            continue

        # ── Text input mode — intercepts all keys, no blocking calls ─────────
        # This runs FIRST so it can't be missed by the elif chain below.
        if renderer.text_input_active:
            if key not in (-1, curses.ERR):
                _process_text_input_key(
                    key, renderer, control_mode, player_entity, moriarty, world_state
                )

        # ── Help overlay: any key dismisses ──────────────────────────────────
        elif renderer.show_help and key not in (-1, curses.ERR):
            renderer.show_help = False

        # ── Global keys ───────────────────────────────────────────────────────
        elif key == ord("q"):
            running = False
            continue
        elif key == ord("?"):
            renderer.show_help = not renderer.show_help
        elif key == ord("["):
            tick_delay_idx = max(0, tick_delay_idx - 1)
            renderer.tick_delay_idx = tick_delay_idx
            renderer.tick_delay = TICK_DELAYS[tick_delay_idx]
            renderer.add_message(f"Mo lag: {TICK_DELAYS[tick_delay_idx]}s")
        elif key == ord("]"):
            tick_delay_idx = min(len(TICK_DELAYS) - 1, tick_delay_idx + 1)
            renderer.tick_delay_idx = tick_delay_idx
            renderer.tick_delay = TICK_DELAYS[tick_delay_idx]
            renderer.add_message(f"Mo lag: {TICK_DELAYS[tick_delay_idx]}s")
        elif key == ord("v"):
            renderer.show_los = not renderer.show_los
            renderer.add_message("LOS overlay ON" if renderer.show_los else "LOS overlay OFF")
        elif key == ord("`"):
            prompt_style_idx = (prompt_style_idx + 1) % len(PROMPT_STYLES)
            renderer.add_message(f"Prompt: {PROMPT_LABELS[prompt_style_idx]}")
        elif key == ord(" "):
            stepped = not stepped
            renderer.stepped = stepped
            renderer.add_message("STEP mode ON — press . to advance" if stepped else "STEP mode OFF")
        elif key == ord(".") and stepped:
            step_requested = True

        # ── TAB: mode transitions ─────────────────────────────────────────────
        elif key == ord("\t"):
            if control_mode == "moriarty":
                control_mode = "awaiting_mode_choice"
                renderer.control_mode_label = "DROP-IN?"
                renderer.add_message("Drop in as:  G = god observer   P = player character   ESC = cancel")
            else:
                if control_mode == "player" and player_entity:
                    renderer.add_message("You step back. Your figure stays.")
                elif control_mode == "god":
                    renderer.add_message("Back to observation.")
                control_mode = "moriarty"
                renderer.control_mode_label = "MORIARTY"
                renderer.center_on(moriarty.x, moriarty.y)

        # ── T key: open non-blocking text input ───────────────────────────────
        elif key in (ord("t"), ord("T")):
            if control_mode == "god":
                renderer.text_input_active = True
                renderer.text_input_prompt = "Inject [ENVIRONMENT]"
                renderer.text_input_mode = "god_inject"
                renderer.text_input_buffer = []
            elif control_mode == "player" and player_entity:
                renderer.text_input_active = True
                renderer.text_input_prompt = f"Say (as {player_entity.name})"
                renderer.text_input_mode = "player_talk"
                renderer.text_input_buffer = []
            elif control_mode == "awaiting_mode_choice":
                renderer.add_message("Choose G or P first, then t to talk.")
            else:
                renderer.add_message("TAB then P (player) or G (god) first, then t.")

        # ── Drop-in mode selection ────────────────────────────────────────────
        elif control_mode == "awaiting_mode_choice":
            if key == ord("g"):
                control_mode = "god"
                renderer.control_mode_label = "GOD"
                renderer.add_message("GOD MODE — invisible. t:inject  arrows:pan  m:jump to Mo")
            elif key == ord("p"):
                if player_entity is None:
                    px, py = _find_player_spawn(world_state)
                    player_entity = PlayerEntity(name="figure", x=px, y=py)
                    world_state.add_entity(player_entity)
                    world_state.pending_messages.append({
                        "from_name": "world",
                        "to_id": "broadcast",
                        "message": "A figure appears nearby.",
                        "tick": world_state.tick,
                    })
                    renderer.add_message(f"You appear at ({px},{py}) as a figure.")
                control_mode = "player"
                renderer.control_mode_label = "PLAYER"
                renderer.center_on(player_entity.x, player_entity.y)
                renderer.add_message("PLAYER MODE — arrows:move  t:talk  p:pickup  .:wait")
            elif key == 27:  # ESC cancels
                control_mode = "moriarty"
                renderer.control_mode_label = "MORIARTY"
                renderer.add_message("Drop-in cancelled.")

        # ── God mode: camera panning ──────────────────────────────────────────
        elif control_mode == "god":
            _ext = 500_000
            if key in (curses.KEY_UP, ord("w"), ord("k")):
                renderer.view_y = max(-_ext, renderer.view_y - 3)
            elif key in (curses.KEY_DOWN, ord("s"), ord("j")):
                renderer.view_y = min(_ext, renderer.view_y + 3)
            elif key in (curses.KEY_LEFT, ord("a"), ord("h")):
                renderer.view_x = max(-_ext, renderer.view_x - 3)
            elif key in (curses.KEY_RIGHT, ord("d"), ord("l")):
                renderer.view_x = min(_ext, renderer.view_x + 3)
            elif key == ord("m"):
                renderer.center_on(moriarty.x, moriarty.y)
                renderer.add_message("Jumped to Moriarty.")

        # ── Player mode: avatar actions ───────────────────────────────────────
        elif control_mode == "player" and player_entity:
            if key in MOVE_KEYS:
                moved = _player_move(player_entity, MOVE_KEYS[key], world_state, renderer)
                if moved:
                    renderer.center_on(player_entity.x, player_entity.y)
                    world_state.advance_tick()
            elif key == ord("p"):
                items = world_state.get_items_at(player_entity.x, player_entity.y)
                if items:
                    item = items[0]
                    player_entity.inventory.append(item)
                    world_state.remove_entity(item)
                    renderer.add_message(f"You pick up {item.name}.")
                    world_state.advance_tick()
                else:
                    renderer.add_message("Nothing to pick up here.")
            elif key == ord("."):
                renderer.add_message("You wait.")
                world_state.advance_tick()
            elif key == ord("e"):
                near = world_state.get_objects_near(player_entity.x, player_entity.y, radius=3)
                renderer.add_message(
                    "Nearby: " + ", ".join(o.name for o in near[:4]) if near
                    else "Nothing notable close by."
                )

        # ── Moriarty's AI — runs freely, gated by mo_idle_until timestamp ─────
        now = time.monotonic()
        if not moriarty_thinking and now >= mo_idle_until:
            if not stepped or step_requested:
                step_requested = False
                moriarty_result_holder.clear()
                moriarty_thinking = True
                _perception = world_state.build_perception_block()
                _t = threading.Thread(target=moriarty_think_async,
                                      args=(_perception, moriarty_result_holder,
                                            PROMPT_STYLES[prompt_style_idx]), daemon=True)
                _t.start()

        if moriarty_thinking and moriarty_result_holder:
            moriarty_thinking = False
            _process_moriarty_result(
                moriarty_result_holder[0], moriarty, world_state, renderer,
                follow_mo=(control_mode == "moriarty"),
                prompt_label=PROMPT_LABELS[prompt_style_idx],
            )
            if player_entity:
                world_state.pending_messages = [
                    m for m in world_state.pending_messages
                    if m["to_id"] != player_entity.id
                ]
            # Gate next cycle — no blocking sleep; main loop stays responsive
            if not stepped:
                mo_idle_until = time.monotonic() + TICK_DELAYS[tick_delay_idx]

        renderer.draw(world_state)
        time.sleep(0.033)   # 30 fps frame rate — always runs, never blocked by Mo

      except (curses.error, SystemError):
          # Terminal size mismatch, bad draw position, or ncurses internal error
          try:
              stdscr.clear()
          except Exception:
              pass
      except Exception as e:
          log.error(f"curses loop error: {e}", exc_info=True)

    # Restore previous SIGWINCH handler before handing terminal back
    try:
        if _old_sigwinch is not None:
            signal.signal(signal.SIGWINCH, _old_sigwinch)
    except Exception:
        pass

    save_world(world_state, _config.SAVE_FILE)

# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    # ── Load config and show startup menu ────────────────────────────────────
    cfg      = _config.load()
    si       = save_info(_config.SAVE_FILE)
    decision = _show_menu(cfg, si)
    cfg      = decision["config"]

    # Apply model from config before any Ollama calls
    moriarty_brain.MODEL = cfg["model"]

    if decision["action"] == "quit":
        print("[MORIARTY] Bye.")
        return

    # ── Build or restore world ───────────────────────────────────────────────
    if decision["action"] == "resume" and si:
        print("[MORIARTY] Loading saved world...")
        try:
            world_state = load_world(_config.SAVE_FILE)
            sx, sy = world_state.moriarty.x, world_state.moriarty.y
        except IncompatibleSaveError as e:
            print(f"\n[!] {e}")
            print("[MORIARTY] Starting a new world instead.\n")
            world_state, sx, sy = _init_world(seed=cfg["seed"])
    else:
        world_state, sx, sy = _init_world(seed=cfg["seed"])

    # Persist any config changes (model, seed)
    _config.save(cfg)

    # ── Launch game ──────────────────────────────────────────────────────────
    if USE_CURSES:
        import curses
        print("[MORIARTY] Terminal mode (curses). Press Q to quit.")
        curses.wrapper(run_curses, world_state, sx, sy, cfg)
    else:
        print("[MORIARTY] Graphical mode (pygame).")
        run_pygame(world_state, sx, sy, cfg)

    print("[MORIARTY] Goodbye.")


if __name__ == "__main__":
    run()
