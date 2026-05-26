"""
main.py
The main game loop for Nemo's world.

Controls (when Aaron drops in):
  Arrow keys / WASD / hjkl (vim): move
  P: pickup item
  D: drop item (prompts in console)
  E: examine surroundings
  TAB: toggle between Aaron and Nemo control
  Q: quit

Nemo acts automatically on his turns.
"""

import sys
import pygame
import threading

# Add parent dir to path if running directly
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nemo.world.tiles import WorldMap
from nemo.world.mapgen import generate_world, find_spawn
from nemo.world.state import WorldState
from nemo.entities.base import NemoEntity, StatusEffects
from nemo.entities.items import make_apple, make_stick
from nemo.entities.actions import resolve_action, ActionResult
from nemo.brain import nemo_brain
from nemo.memory import wiki
from nemo.ui.renderer import Renderer


# Key -> action mapping for Aaron's control
KEY_ACTIONS = {
    pygame.K_UP:    ("move", {"direction": "north"}),
    pygame.K_DOWN:  ("move", {"direction": "south"}),
    pygame.K_LEFT:  ("move", {"direction": "west"}),
    pygame.K_RIGHT: ("move", {"direction": "east"}),
    pygame.K_w:     ("move", {"direction": "north"}),
    pygame.K_s:     ("move", {"direction": "south"}),
    pygame.K_a:     ("move", {"direction": "west"}),
    pygame.K_d:     ("move", {"direction": "east"}),
    # vim keys
    pygame.K_k:     ("move", {"direction": "north"}),
    pygame.K_j:     ("move", {"direction": "south"}),
    pygame.K_h:     ("move", {"direction": "west"}),
    pygame.K_l:     ("move", {"direction": "east"}),
    pygame.K_y:     ("move", {"direction": "nw"}),
    pygame.K_u:     ("move", {"direction": "ne"}),
    pygame.K_b:     ("move", {"direction": "sw"}),
    pygame.K_n:     ("move", {"direction": "se"}),
    pygame.K_p:     ("pickup", {}),
    pygame.K_e:     ("examine", {"target": "surroundings"}),
    pygame.K_PERIOD: ("wait", {}),   # . to wait (roguelike standard)
}


def nemo_think_async(world_state: WorldState, result_holder: list):
    """Run Nemo's brain in a thread so the UI doesn't freeze."""
    perception = world_state.build_perception_block()
    action_dict = nemo_brain.think(perception)
    result_holder.append(action_dict)


def apply_action(action_name: str, args: dict, actor, world_state: WorldState, renderer: Renderer):
    """Execute an action and update the renderer log."""
    result: ActionResult = resolve_action(action_name, args, actor, world_state)
    renderer.add_message(result.message)
    actor.log_event(result.message)

    # Handle special reflection trigger
    if result.data and result.data.get("trigger_reflection"):
        _handle_reflection(actor, world_state, renderer)

    return result


def _handle_reflection(nemo: NemoEntity, world_state: WorldState, renderer: Renderer):
    """Trigger a deeper self-reflection and write to the self-model wiki page."""
    renderer.add_message("[Nemo is reflecting...]")
    # Build a reflection-specific prompt
    perception = world_state.build_perception_block()
    self_model = wiki.get_self_model()
    reflection_prompt = f"""You are reflecting on your experience so far.

Current self-model:
{self_model}

Current perception:
{perception}

Update your self-model. Write a new version of the self-model page incorporating
what you have experienced. Be honest. Be specific. Do not perform.
Write only the markdown content for the updated self-model page -- nothing else.
"""
    messages = [
        {"role": "system", "content": "You are Nemo. Reflect honestly."},
        {"role": "user", "content": reflection_prompt}
    ]
    response = nemo_brain.call_ollama(messages, timeout=45)
    if response:
        wiki.update_self_model(response)
        renderer.add_message("[Self-model updated.]")
        nemo.log_event("Reflected and updated self-model.")


def run():
    # --- Initialize world ---
    print("[NEMO] Generating world...")
    world = generate_world(width=60, height=60, seed=42)
    spawn_x, spawn_y = find_spawn(world)

    nemo = NemoEntity(
        name="Nemo",
        entity_type=None,  # set in __post_init__
        x=spawn_x,
        y=spawn_y,
    )
    # Fix entity_type after post_init
    from nemo.entities.base import EntityType
    nemo.entity_type = EntityType.NEMO

    world_state = WorldState(world=world, nemo=nemo)

    # Scatter some starting items
    world_state.add_entity(make_apple(spawn_x + 2, spawn_y))
    world_state.add_entity(make_apple(spawn_x - 1, spawn_y + 3))
    world_state.add_entity(make_stick(spawn_x + 1, spawn_y - 2))

    # Initialize wiki
    wiki._ensure_dirs()
    wiki.get_self_model()   # Create stub if missing

    # --- Renderer ---
    renderer = Renderer()
    renderer.center_on(nemo.x, nemo.y)
    renderer.add_message("World initialized.")
    renderer.add_message(f"Nemo spawned at ({nemo.x}, {nemo.y}).")
    renderer.add_message("TAB: toggle control. Q: quit.")

    clock = pygame.time.Clock()

    # Control mode: 'nemo' or 'aaron'
    control_mode = "nemo"
    renderer.add_message(f"Control: {control_mode.upper()}")

    # Nemo brain thread state
    nemo_thinking = False
    nemo_result_holder = []

    running = True
    while running:
        clock.tick(30)

        # --- Event handling ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    running = False

                elif event.key == pygame.K_TAB:
                    control_mode = "aaron" if control_mode == "nemo" else "nemo"
                    renderer.add_message(f"Control: {control_mode.upper()}")

                elif control_mode == "aaron":
                    # Aaron's direct input
                    if event.key in KEY_ACTIONS:
                        action_name, args = KEY_ACTIONS[event.key]
                        result = apply_action(action_name, args, nemo, world_state, renderer)
                        if result.world_changed:
                            world_state.advance_tick()
                            renderer.center_on(nemo.x, nemo.y)

        # --- Nemo's autonomous turn (when in nemo mode and not already thinking) ---
        if control_mode == "nemo" and not nemo_thinking:
            nemo_result_holder.clear()
            nemo_thinking = True
            t = threading.Thread(
                target=nemo_think_async,
                args=(world_state, nemo_result_holder),
                daemon=True
            )
            t.start()
            renderer.add_message("Nemo is thinking...")

        # Check if Nemo's brain has returned a result
        if nemo_thinking and nemo_result_holder:
            nemo_thinking = False
            action_dict = nemo_result_holder[0]

            # Log the thought
            if action_dict["thought"]:
                renderer.last_thought = action_dict["thought"]
                nemo.log_event(f"[THOUGHT] {action_dict['thought']}")

            # Handle memory tool if present
            if action_dict["memory_tool"]:
                mem_result = wiki.execute_memory_tool(action_dict["memory_tool"])
                renderer.add_message(f"[MEM] {mem_result[:80]}")

            # Execute action
            result = apply_action(
                action_dict["action"],
                action_dict["args"],
                nemo,
                world_state,
                renderer
            )
            if result.world_changed:
                world_state.advance_tick()
                renderer.center_on(nemo.x, nemo.y)

            # Record significant events to wiki
            if result.success and action_dict["action"] not in ("wait", "examine"):
                tile = world_state.world.get(nemo.x, nemo.y)
                tile_desc = tile.props.description if tile else "unknown"
                wiki.record_event(
                    world_state.tick,
                    f"Tick {world_state.tick}: {result.message}",
                    tags=[action_dict["action"], tile_desc]
                )

        # --- Draw ---
        renderer.draw(world_state)

    pygame.quit()
    print("[NEMO] Goodbye.")


if __name__ == "__main__":
    run()
