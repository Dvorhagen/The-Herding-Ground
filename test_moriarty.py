#!/usr/bin/env python3
"""
test_moriarty.py
Headless test harness for Moriarty's brain — no renderer required.

Runs Mo through configurable scenarios, printing full perception blocks
and raw LLM responses for analysis. Useful for:
  - Checking whether prompt changes actually improve behaviour
  - Running scripted conversations as the "figure" player entity
  - Comparing prompt styles on identical scenarios
  - Catching reasoning loops, spatial errors, self-conversation

Usage:
  python test_moriarty.py                          # base scenario, 5 ticks, structured
  python test_moriarty.py --ticks 10               # more ticks
  python test_moriarty.py --scenario wounded        # Mo has a bleeding arm wound
  python test_moriarty.py --scenario conversation   # figure nearby, scripted chat
  python test_moriarty.py --scenario forest         # deep in forest with animals
  python test_moriarty.py --scenario combat         # adjacent deer, knife equipped
  python test_moriarty.py --style framed            # use FRAMED prompt
  python test_moriarty.py --compare                 # run all 3 styles, same scenario
  python test_moriarty.py --verbose                 # print full perception blocks
  python test_moriarty.py --raw                     # print raw LLM output

Scenarios: base, wounded, conversation, forest, combat, cave
"""

import sys
import os
import argparse
import time
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from moriarty.world.mapgen import generate_world, find_spawn
from moriarty.world.state import WorldState
from moriarty.world.objects import make_campfire, make_boulder, make_tree
from moriarty.world.tiles import TileType
from moriarty.entities.base import MoriartyEntity, PlayerEntity, EntityType
from moriarty.entities.items import make_apple, make_stick, make_stone, make_berries
from moriarty.entities.animals import make_deer, make_fox, make_rabbit
from moriarty.entities.combat import Wound, BodyPart, WoundSeverity
from moriarty.entities.actions import resolve_action
from moriarty.brain import moriarty_brain
from moriarty.brain.moriarty_brain import PROMPT_STYLES, PROMPT_LABELS


# ── Scenario builder ──────────────────────────────────────────────────────────

def build_scenario(name: str, seed: int = 42) -> tuple:
    """
    Return (world_state, player_entity_or_None, conversation_script).
    conversation_script: list of (at_tick, message_text) the "figure" sends.
    """
    world = generate_world(64, 64, seed=seed)
    sx, sy = find_spawn(world)
    mo = MoriartyEntity(name="Moriarty", entity_type=EntityType.MORIARTY, x=sx, y=sy)
    ws = WorldState(world=world, moriarty=mo)
    mo.status.hunger = 65
    mo.status.fatigue = 20
    player = None
    script = []

    if name == "base":
        ws.add_object(make_campfire(sx + 2, sy))
        ws.add_entity(make_apple(sx + 1, sy))
        ws.add_entity(make_stick(sx, sy + 1))
        ws.add_entity(make_stone(sx - 1, sy))

    elif name == "wounded":
        ws.add_object(make_campfire(sx + 1, sy))
        ws.add_entity(make_apple(sx, sy + 1))
        wound = Wound(part=BodyPart.RIGHT_ARM, severity=WoundSeverity.CUT)
        mo.combat_state.apply_wound(wound)
        mo.combat_state.blood_loss = 20
        mo.status.mood = "pained"

    elif name == "conversation":
        player = PlayerEntity(name="figure", x=sx + 2, y=sy)
        ws.add_entity(player)
        ws.add_object(make_campfire(sx, sy + 1))
        # Scripted conversation: (tick_number, message_text)
        script = [
            (0, "Hello. Can you hear me?"),
            (2, "What do you remember about this place?"),
            (4, "Are you afraid of me?"),
            (6, "I mean you no harm."),
        ]

    elif name == "forest":
        # Find a forest tile and move Mo there
        for dy in range(-25, 26):
            for dx in range(-25, 26):
                tile = world.get(sx + dx, sy + dy)
                if tile and tile.tile_type == TileType.FOREST:
                    mo.x = sx + dx
                    mo.y = sy + dy
                    break
            else:
                continue
            break
        ws.add_entity(make_rabbit(mo.x + 1, mo.y))
        ws.add_entity(make_deer(mo.x - 2, mo.y + 1))
        ws.add_entity(make_fox(mo.x + 3, mo.y - 1))
        ws.add_entity(make_berries(mo.x, mo.y))

    elif name == "combat":
        mo.inventory.append(make_stone(sx, sy))
        mo.inventory.append(make_stick(sx, sy))
        resolve_action('craft', {'recipe': 'stone knife'}, mo, ws)
        resolve_action('equip', {'item_name': 'stone knife'}, mo, ws)
        ws.add_entity(make_deer(sx + 1, sy))
        ws.add_entity(make_fox(sx - 1, sy + 1))

    elif name == "cave":
        # Find cave floor tile
        for dy in range(-25, 26):
            for dx in range(-25, 26):
                tile = world.get(sx + dx, sy + dy)
                if tile and tile.tile_type == TileType.CAVE_FLOOR:
                    mo.x = sx + dx
                    mo.y = sy + dy
                    break
            else:
                continue
            break
        mo.status.fatigue = 60
        mo.status.mood = "uneasy"

    else:
        print(f"Unknown scenario '{name}'. Using 'base'.")

    return ws, player, script


# ── Tick runner ───────────────────────────────────────────────────────────────

def run_tick(ws, style, inject_msg=None):
    """Run one Mo tick. Returns (result_dict, action_result, perception_text)."""
    mo = ws.moriarty
    if inject_msg:
        ws.pending_messages.append({
            "from_name": inject_msg["from"],
            "to_id":     mo.id,
            "message":   inject_msg["text"],
            "tick":      ws.tick,
        })
    perception = ws.build_perception_block()
    result = moriarty_brain.think(perception, style=style)
    action_result = resolve_action(result["action"], result["args"], mo, ws)
    if action_result.world_changed:
        ws.advance_tick()
    else:
        ws.tick += 1
        ws.moriarty.status.tick()
    return result, action_result, perception


# ── Output formatting ─────────────────────────────────────────────────────────

DIVIDER     = "─" * 64
BIG_DIVIDER = "═" * 64

def print_tick_result(tick_n, perception, result, action_result,
                      verbose=False, show_raw=False):
    print(f"\n{DIVIDER}")
    print(f"  TICK {tick_n}")
    print(DIVIDER)

    if verbose:
        print("\n[PERCEPTION]")
        for line in perception.split("\n"):
            print("  " + line)
        print()

    thought = result["thought"] or "(no thought)"
    print(f"THOUGHT  {textwrap.fill(thought, width=60, subsequent_indent='         ')}")

    action_str = result["action"].upper()
    if result["args"]:
        action_str += "  " + "  ".join(f"{k}={v}" for k, v in result["args"].items())
    print(f"ACTION   {action_str}")

    if result["memory_tool"]:
        mt = result["memory_tool"]
        print(f"MEMORY   {mt.get('tool','?').upper()} {mt.get('category','')}/{mt.get('name','')}")

    outcome = action_result.message
    ok = "✓" if action_result.success else "✗"
    print(f"RESULT   {ok} {textwrap.fill(outcome, width=58, subsequent_indent='         ')}")

    if show_raw and result.get("raw"):
        print("\n[RAW OUTPUT]")
        for line in result["raw"].strip().split("\n"):
            print("  " + line)

    # Flag anything suspicious
    flags = []
    thought_lower = thought.lower()
    if any(w in thought_lower for w in ("args", "action:", "thought:", "memory:", "format")):
        flags.append("⚠ format-awareness in THOUGHT")
    if result["action"] == "wait" and not result["thought"]:
        flags.append("⚠ empty thought + wait — possible parse failure")
    if "endless" in thought_lower or "stretches" in thought_lower:
        flags.append("⚠ possible spatial hallucination")
    if flags:
        for f in flags:
            print(f"FLAG     {f}")


def print_header(scenario, style, ticks):
    print(f"\n{BIG_DIVIDER}")
    print(f"  MORIARTY TEST HARNESS")
    print(f"  scenario={scenario}  style={style}  ticks={ticks}")
    print(f"{BIG_DIVIDER}")


def print_summary(results):
    print(f"\n{BIG_DIVIDER}")
    print("  SUMMARY")
    print(BIG_DIVIDER)
    action_counts = {}
    memory_ops = 0
    flags_total = 0
    for r, ar, _ in results:
        a = r["action"]
        action_counts[a] = action_counts.get(a, 0) + 1
        if r["memory_tool"]:
            memory_ops += 1
    print(f"  Ticks run:    {len(results)}")
    print(f"  Memory ops:   {memory_ops}")
    print(f"  Actions used: {', '.join(f'{a}({n})' for a, n in sorted(action_counts.items(), key=lambda x: -x[1]))}")
    print(BIG_DIVIDER)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Moriarty headless test harness")
    parser.add_argument("--scenario", "-s", default="base",
                        choices=["base", "wounded", "conversation", "forest", "combat", "cave"],
                        help="World scenario to run")
    parser.add_argument("--ticks", "-t", type=int, default=5,
                        help="Number of ticks to run")
    parser.add_argument("--style", default="structured",
                        choices=["structured", "framed", "natural"],
                        help="Prompt style")
    parser.add_argument("--compare", action="store_true",
                        help="Run all 3 prompt styles on the same scenario")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print full perception blocks")
    parser.add_argument("--raw", "-r", action="store_true",
                        help="Print raw LLM output")
    parser.add_argument("--seed", type=int, default=42,
                        help="World seed")
    args = parser.parse_args()

    # Check Ollama
    import requests
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        if not any(moriarty_brain.MODEL in m for m in models):
            print(f"[!] Model '{moriarty_brain.MODEL}' not found. Run: ollama pull {moriarty_brain.MODEL}")
            sys.exit(1)
    except Exception as e:
        print(f"[!] Ollama not reachable: {e}")
        sys.exit(1)

    styles_to_run = PROMPT_STYLES if args.compare else [args.style]

    for style in styles_to_run:
        ws, player, script = build_scenario(args.scenario, seed=args.seed)
        label = PROMPT_LABELS[PROMPT_STYLES.index(style)]
        print_header(args.scenario, label, args.ticks)

        results = []
        for tick in range(args.ticks):
            # Check for scripted player message at this tick
            inject = None
            for (at_tick, msg_text) in script:
                if at_tick == tick:
                    inject = {"from": player.name if player else "figure", "text": msg_text}
                    print(f"\n  [figure → Mo]: \"{msg_text}\"")
                    break

            t0 = time.monotonic()
            result, action_result, perception = run_tick(ws, style, inject_msg=inject)
            elapsed = time.monotonic() - t0

            print_tick_result(tick + 1, perception, result, action_result,
                              verbose=args.verbose, show_raw=args.raw)
            print(f"         ({elapsed:.1f}s)")
            results.append((result, action_result, perception))

        print_summary(results)

        if args.compare and style != styles_to_run[-1]:
            input("\n  [Press Enter to run next style...]")


if __name__ == "__main__":
    main()
