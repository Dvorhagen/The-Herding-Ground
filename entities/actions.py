"""
entities/actions.py
The action system. All entity actions are defined here as functions
that take (actor, world_state) and return an ActionResult.

Moriarty's brain outputs an action name + optional args.
The action resolver looks up the function here and executes it.

To add new actions: define a function, add it to ACTION_REGISTRY.
"""

from dataclasses import dataclass
from typing import Optional, Any
from .base import DIRECTIONS


@dataclass
class ActionResult:
    """
    The result of executing an action.
    success: did it work?
    message: what happened (fed back into Moriarty's context)
    world_changed: does the renderer need to redraw?
    """
    success: bool
    message: str
    world_changed: bool = True
    data: Any = None    # Optional extra payload for special actions


def action_move(actor, args: dict, world_state) -> ActionResult:
    """Move in a direction. args: {direction: str}"""
    direction = args.get("direction", "").lower()
    if direction not in DIRECTIONS:
        return ActionResult(False, f"Unknown direction: '{direction}'. Valid: {list(DIRECTIONS.keys())}")
    dx, dy = DIRECTIONS[direction]
    nx, ny = actor.x + dx, actor.y + dy
    blocking_objects = [o for o in world_state.get_objects_at(nx, ny) if o.blocks]
    if blocking_objects:
        return ActionResult(False, f"Can't move {direction} — {blocking_objects[0].name} is in the way.", world_changed=False)
    if actor.move(dx, dy, world_state.world):
        actor.hidden = False   # movement breaks concealment
        tile = world_state.world.get(actor.x, actor.y)
        tile_desc = tile.props.description if tile else "unknown ground"
        msg = f"Moved {direction}. Underfoot: {tile_desc}."
        items_here = world_state.get_items_at(actor.x, actor.y)
        if items_here:
            msg += f" You see here: {', '.join(i.name for i in items_here)}."
        return ActionResult(True, msg)
    else:
        tile = world_state.world.get(nx, ny)
        obstacle = tile.props.description if tile else "the edge of the world"
        return ActionResult(False, f"Can't move {direction} — blocked by {obstacle}.", world_changed=False)


def action_pickup(actor, args: dict, world_state) -> ActionResult:
    """Pick up an item at current location. args: {item_name: str} or picks first available."""
    items_here = world_state.get_items_at(actor.x, actor.y)
    if not items_here:
        return ActionResult(False, "There's nothing here to pick up.", world_changed=False)
    target_name = args.get("item_name", "").lower()
    if target_name:
        item = next((i for i in items_here if i.name.lower() == target_name), None)
        if not item:
            return ActionResult(False, f"No '{target_name}' here. You see: {', '.join(i.name for i in items_here)}.", world_changed=False)
    else:
        item = items_here[0]
    world_state.remove_entity(item)
    actor.inventory.append(item)
    return ActionResult(True, f"Picked up: {item.name}. {item.description}.")


def action_drop(actor, args: dict, world_state) -> ActionResult:
    """Drop an item. args: {item_name: str}"""
    if not actor.inventory:
        return ActionResult(False, "You're not carrying anything.", world_changed=False)
    target_name = args.get("item_name", "").lower()
    item = next((i for i in actor.inventory if i.name.lower() == target_name), None)
    if not item:
        names = [i.name for i in actor.inventory]
        return ActionResult(False, f"You don't have '{target_name}'. Carrying: {', '.join(names)}.", world_changed=False)
    actor.inventory.remove(item)
    item.x, item.y = actor.x, actor.y
    world_state.add_entity(item)
    return ActionResult(True, f"Dropped {item.name}.")


def action_use(actor, args: dict, world_state) -> ActionResult:
    """Use an item from inventory. args: {item_name: str}"""
    if not actor.inventory:
        return ActionResult(False, "You have nothing to use.", world_changed=False)
    target_name = args.get("item_name", "").lower()
    item = next((i for i in actor.inventory if i.name.lower() == target_name), None)
    if not item:
        return ActionResult(False, f"You don't have '{target_name}'.", world_changed=False)
    if not item.usable:
        return ActionResult(False, f"You can't use the {item.name} that way.", world_changed=False)
    msg = item.on_use(actor, world_state)
    if hasattr(item, 'item_type') and item.item_type.name == 'FOOD':
        actor.inventory.remove(item)
    return ActionResult(True, msg)


def action_examine(actor, args: dict, world_state) -> ActionResult:
    """Examine surroundings or a specific thing. args: {target: str} optional"""
    target = args.get("target", "").lower()
    if not target or target in ("surroundings", "area", "around"):
        desc = world_state.world.describe_surroundings(actor.x, actor.y)
        entities_nearby = world_state.get_entities_near(actor.x, actor.y, radius=3)
        entity_desc = "\n".join(e.describe() for e in entities_nearby if e.id != actor.id)
        objects_nearby = world_state.get_objects_near(actor.x, actor.y, radius=3)
        object_desc = "\n".join(o.describe() for o in objects_nearby)
        full = desc
        if entity_desc:
            full += f"\nNearby entities:\n{entity_desc}"
        if object_desc:
            full += f"\nWorld objects:\n{object_desc}"
        return ActionResult(True, full, world_changed=False)
    # Try world objects first, then entities
    nearby_objects = world_state.get_objects_near(actor.x, actor.y, radius=5)
    found_obj = next((o for o in nearby_objects if target in o.name.lower()), None)
    if found_obj:
        return ActionResult(True, found_obj.describe(), world_changed=False)
    nearby = world_state.get_entities_near(actor.x, actor.y, radius=5)
    found = next((e for e in nearby if target in e.name.lower()), None)
    if found:
        return ActionResult(True, found.describe(), world_changed=False)
    return ActionResult(False, f"You don't see any '{target}' nearby.", world_changed=False)


def action_wait(actor, args: dict, world_state) -> ActionResult:
    """Do nothing for one tick."""
    return ActionResult(True, "You wait and observe.", world_changed=False)


def action_sleep(actor, args: dict, world_state) -> ActionResult:
    """Deep rest. Recovers fatigue substantially. Triggers dreaming hook."""
    if actor.status.fatigue < 10:
        return ActionResult(False, "You're not tired enough to sleep.", world_changed=False)
    recovered = min(actor.status.fatigue, 60)
    actor.status.fatigue = max(0, actor.status.fatigue - 60)
    actor.status.hunger = max(0, actor.status.hunger - 5)  # sleeping burns a little
    actor.status.mood = "rested"
    msg = f"You sleep. Deeply, without knowing how long. Fatigue eases by {recovered}."
    near_campfire = any(
        hasattr(o, 'lit') and o.lit
        for o in world_state.get_objects_near(actor.x, actor.y, radius=3)
    )
    if near_campfire:
        msg += " The warmth of the fire keeps the cold away."
    return ActionResult(True, msg, data={"trigger_sleep": True})


def action_drink(actor, args: dict, world_state) -> ActionResult:
    """Drink from an adjacent water tile."""
    from ..world.tiles import TileType
    for dx, dy in ((0, 0), (0, 1), (0, -1), (1, 0), (-1, 0)):
        tile = world_state.world.get(actor.x + dx, actor.y + dy)
        if tile and tile.tile_type == TileType.WATER:
            actor.status.hunger = min(100, actor.status.hunger + 15)
            actor.status.fatigue = max(0, actor.status.fatigue - 5)
            source = "stream" if dy != 0 or dx != 0 else "water at your feet"
            return ActionResult(True, f"You kneel and drink from the {source}. Cold and clean.")
    # Check within 2 tiles and report
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            tile = world_state.world.get(actor.x + dx, actor.y + dy)
            if tile and tile.tile_type == TileType.WATER:
                return ActionResult(False, "Water is close but not quite within reach — move one step closer.", world_changed=False)
    return ActionResult(False, "There's no water nearby to drink from.", world_changed=False)


def action_listen(actor, args: dict, world_state) -> ActionResult:
    """Focus on sound for one tick — returns a richer auditory perception."""
    from ..world.tiles import TileType
    sounds = []
    tile_counts = {}
    for dy in range(-8, 9):
        for dx in range(-8, 9):
            tile = world_state.world.get(actor.x + dx, actor.y + dy)
            if tile:
                tile_counts[tile.tile_type] = tile_counts.get(tile.tile_type, 0) + 1

    if tile_counts.get(TileType.WATER, 0) > 20:
        sounds.append("the rush of water — a river or stream, close")
    elif tile_counts.get(TileType.WATER, 0) > 5:
        sounds.append("water moving somewhere nearby, a soft gurgle")
    if tile_counts.get(TileType.FOREST, 0) > 30:
        sounds.append("birdsong layered through the canopy, insects underneath")
    elif tile_counts.get(TileType.FOREST, 0) > 10:
        sounds.append("the occasional bird call from the treeline")
    if tile_counts.get(TileType.WETLAND, 0) > 10:
        sounds.append("frogs and the steady hum of insects from boggy ground")
    if tile_counts.get(TileType.CAVE_FLOOR, 0) > 0:
        sounds.append("slow dripping somewhere in the dark, a deep silence beneath it")
    if tile_counts.get(TileType.MOUNTAIN, 0) > 10:
        sounds.append("wind moving through high stone, a low resonant moan")
    if not sounds:
        sounds.append("wind across open ground, nothing else")

    # Nearby objects add sound
    nearby_objects = world_state.get_objects_near(actor.x, actor.y, radius=4)
    for obj in nearby_objects:
        if hasattr(obj, 'lit') and obj.lit:
            sounds.append("the soft crackling of fire")
            break

    sound_text = "; ".join(sounds)
    return ActionResult(True, f"You go still and listen.\n{sound_text}.", world_changed=False)


def action_throw(actor, args: dict, world_state) -> ActionResult:
    """Throw a carried item in a direction."""
    if not actor.inventory:
        return ActionResult(False, "You're not carrying anything to throw.", world_changed=False)
    target_name = args.get("item_name", "").lower()
    direction = args.get("direction", "").lower()
    item = next((i for i in actor.inventory if i.name.lower() == target_name), None) if target_name else actor.inventory[0]
    if not item:
        return ActionResult(False, f"You don't have '{target_name}'.", world_changed=False)
    actor.inventory.remove(item)
    # Place item a few tiles in the thrown direction
    from .base import DIRECTIONS
    if direction in DIRECTIONS:
        dx, dy = DIRECTIONS[direction]
        land_x = max(0, min(world_state.world.width - 1, actor.x + dx * 4))
        land_y = max(0, min(world_state.world.height - 1, actor.y + dy * 4))
    else:
        land_x, land_y = actor.x, actor.y
    item.x, item.y = land_x, land_y
    world_state.add_entity(item)
    dir_str = f" to the {direction}" if direction else ""
    return ActionResult(True, f"You hurl the {item.name}{dir_str}. It lands with a thud.")


def action_dig(actor, args: dict, world_state) -> ActionResult:
    """Dig into the ground. Costs fatigue; chance of finding a stone."""
    from ..world.tiles import TileType
    import random
    tile = world_state.world.get(actor.x, actor.y)
    diggable = (TileType.GRASS, TileType.WETLAND, TileType.SAND, TileType.ROCKY)
    if not tile or tile.tile_type not in diggable:
        return ActionResult(False, "The ground here is too hard to dig into.", world_changed=False)
    actor.status.fatigue = min(100, actor.status.fatigue + 8)
    if random.random() < 0.35:
        from ..entities.items import make_stone
        stone = make_stone(actor.x, actor.y)
        actor.inventory.append(stone)
        return ActionResult(True, "You dig into the earth and turn up a smooth stone. You pocket it.")
    return ActionResult(True, "You dig into the earth — soil and roots, nothing else. Your hands are dirty.")


def action_equip(actor, args: dict, world_state) -> ActionResult:
    """Equip an item from inventory. args: {item_name: str}"""
    target = args.get("item_name", "").lower()
    if not target:
        return ActionResult(False, f"Equip what? Carrying: {actor.describe_inventory()}", world_changed=False)
    item = next((i for i in actor.inventory if target in i.name.lower()), None)
    if not item:
        return ActionResult(False, f"You don't have '{target}'.", world_changed=False)
    msg = actor.equip(item)
    return ActionResult(True, msg)


def action_unequip(actor, args: dict, world_state) -> ActionResult:
    """Unequip from a slot. args: {slot: str} or {item_name: str}"""
    slot = args.get("slot", args.get("item_name", "")).lower()
    # Allow item name instead of slot name
    if slot and slot not in actor.equipment:
        for s, item in actor.equipment.items():
            if item and slot in item.name.lower():
                slot = s
                break
    msg = actor.unequip(slot)
    return ActionResult(True if "Unequipped" in msg else False, msg,
                        world_changed="Unequipped" in msg)


def action_craft(actor, args: dict, world_state) -> ActionResult:
    """Craft an item from inventory components."""
    from .crafting import RECIPES, can_craft, consume_inputs
    recipe_name = (args.get("recipe") or args.get("item_name") or "").lower().strip()

    if not recipe_name:
        counts = {}
        for item in actor.inventory:
            counts[item.name.lower()] = counts.get(item.name.lower(), 0) + 1
        lines = []
        for name, recipe in RECIPES.items():
            ok, reason = can_craft(actor.inventory, recipe)
            needs = ", ".join(f"{v}× {k}" for k, v in recipe["inputs"].items())
            mark = "✓" if ok else "✗"
            lines.append(f"  {mark} {name}: {recipe['description']} [{needs}]")
        return ActionResult(True, "Known recipes:\n" + "\n".join(lines), world_changed=False)

    # Fuzzy match recipe name
    match = next((n for n in RECIPES if recipe_name in n), None)
    if not match:
        return ActionResult(False, f"Unknown recipe '{recipe_name}'. Use 'craft' to list all.", world_changed=False)
    recipe = RECIPES[match]
    ok, reason = can_craft(actor.inventory, recipe)
    if not ok:
        return ActionResult(False, f"Can't craft {match}. {reason}.", world_changed=False)
    consume_inputs(actor.inventory, recipe)
    item = recipe["output"](actor.x, actor.y)
    actor.inventory.append(item)
    return ActionResult(True, f"You craft a {item.name}. {item.description}.")


def action_attack(actor, args: dict, world_state) -> ActionResult:
    """Full combat exchange: Mo attacks, animal counter-attacks.
    args: {target: str, part: str (optional body part)}"""
    from .animals import Animal
    from .combat import (resolve_attack, BODY_PART_LOOKUP,
                         MORIARTY_STATS, ANIMAL_STATS)

    target_name = (args.get("target") or args.get("item_name") or "").lower()
    part_name   = (args.get("part") or "").lower().strip()

    nearby = [e for e in world_state.get_entities_near(actor.x, actor.y, radius=2)
              if isinstance(e, Animal) and e.alive]
    if target_name:
        nearby = [e for e in nearby if target_name in e.name.lower()]
    if not nearby:
        return ActionResult(False, "Nothing to attack nearby.", world_changed=False)
    target = min(nearby, key=lambda e: (e.x - actor.x)**2 + (e.y - actor.y)**2)

    weapon   = actor.equipment.get("weapon")
    w_damage = getattr(weapon, 'damage', 2)
    target_part = BODY_PART_LOOKUP.get(part_name)

    msg = resolve_attack(
        actor.combat_state, target, target_part, w_damage, world_state
    )
    return ActionResult(True, msg)


def action_grapple(actor, args: dict, world_state) -> ActionResult:
    """Attempt to seize and hold a nearby animal. Must be adjacent."""
    from .animals import Animal
    from .combat import resolve_grapple

    target_name = (args.get("target") or args.get("item_name") or "").lower()
    adjacent = [e for e in world_state.get_entities_near(actor.x, actor.y, radius=1)
                if isinstance(e, Animal) and e.alive]
    if target_name:
        adjacent = [e for e in adjacent if target_name in e.name.lower()]
    if not adjacent:
        return ActionResult(False, "Nothing close enough to grapple — move adjacent first.", world_changed=False)
    target = adjacent[0]
    msg = resolve_grapple(actor.combat_state, target)
    return ActionResult(True, msg)


def action_break_grapple(actor, args: dict, world_state) -> ActionResult:
    """Attempt to break free from a grapple."""
    from .combat import resolve_break_grapple
    msg = resolve_break_grapple(actor.combat_state)
    return ActionResult("free" in msg.lower() or "wrench" in msg.lower(), msg,
                        world_changed=False)


def action_dodge(actor, args: dict, world_state) -> ActionResult:
    """Take a defensive stance — increases dodge chance on the next hit."""
    from .combat import resolve_dodge
    msg = resolve_dodge(actor.combat_state)
    return ActionResult(True, msg, world_changed=False)


def action_flee_combat(actor, args: dict, world_state) -> ActionResult:
    """Attempt to disengage from combat and put distance between you and the fight."""
    from .combat import resolve_flee_combat
    success, msg = resolve_flee_combat(actor.combat_state, actor, world_state)
    if success:
        # Move 2-3 tiles away from grappled/nearest enemy
        from .animals import Animal
        from .base import DIRECTIONS
        enemies = [e for e in world_state.get_entities_near(actor.x, actor.y, radius=5)
                   if isinstance(e, Animal) and e.alive]
        if enemies:
            nearest = min(enemies, key=lambda e: (e.x - actor.x)**2 + (e.y - actor.y)**2)
            dx = actor.x - nearest.x
            dy = actor.y - nearest.y
            for _ in range(3):
                sx = (1 if dx > 0 else -1) if abs(dx) > 0 else 0
                sy = (1 if dy > 0 else -1) if abs(dy) > 0 else 0
                actor.move(sx or 1, sy, world_state.world)
    return ActionResult(success, msg, world_changed=success)


def action_reflect(actor, args: dict, world_state) -> ActionResult:
    """
    Special action: Moriarty pauses to reflect on its state.
    This will trigger a memory-write check.
    """
    return ActionResult(True, "REFLECT", world_changed=False, data={"trigger_reflection": True})


# Registry maps action name strings (from LLM output) to handler functions
ACTION_REGISTRY = {
    "move":    action_move,
    "go":      action_move,
    "walk":    action_move,
    "pickup":  action_pickup,
    "pick up": action_pickup,
    # "take" routes dynamically to world objects (e.g. chest.take)
    "drop":    action_drop,
    "use":     action_use,
    "eat":     action_use,
    "examine": action_examine,
    "look":    action_examine,
    "wait":    action_wait,
    "rest":    action_wait,
    "sleep":    action_sleep,
    "drink":    action_drink,
    "listen":   action_listen,
    "throw":    action_throw,
    "hurl":     action_throw,
    "dig":      action_dig,
    "equip":    action_equip,
    "wear":     action_equip,
    "wield":    action_equip,
    "unequip":  action_unequip,
    "remove":   action_unequip,
    "craft":    action_craft,
    "make":     action_craft,
    "attack":        action_attack,
    "strike":        action_attack,
    "hit":           action_attack,
    "grapple":       action_grapple,
    "grab":          action_grapple,
    "seize":         action_grapple,
    "break grapple": action_break_grapple,
    "break free":    action_break_grapple,
    "dodge":         action_dodge,
    "parry":         action_dodge,
    "flee combat":   action_flee_combat,
    "disengage":     action_flee_combat,
    "reflect":       action_reflect,
}


def resolve_action(action_name: str, args: dict, actor, world_state) -> ActionResult:
    """Look up and execute an action by name.

    First checks the fixed ACTION_REGISTRY. If not found, searches nearby world
    objects and entities for one whose interactions() dict exposes that verb.
    """
    key = action_name.lower().strip()
    handler = ACTION_REGISTRY.get(key)
    if handler is not None:
        return handler(actor, args, world_state)

    # Dynamic fallback: find a world object or entity that supports this verb.
    target_name = (args.get("target") or args.get("item_name") or "").lower()

    nearby_objects = world_state.get_objects_near(actor.x, actor.y, radius=2)
    for obj in nearby_objects:
        if target_name and target_name not in obj.name.lower():
            continue
        obj_interactions = obj.interactions()
        if key in obj_interactions:
            return obj_interactions[key](actor, args, world_state)

    nearby_entities = world_state.get_entities_near(actor.x, actor.y, radius=2)
    for entity in nearby_entities:
        if entity.id == actor.id:
            continue
        if target_name and target_name not in entity.name.lower():
            continue
        if hasattr(entity, "interactions"):
            entity_interactions = entity.interactions()
            if key in entity_interactions:
                return entity_interactions[key](actor, args, world_state)

    available = list(ACTION_REGISTRY.keys()) + ["(object verbs: open, warm, take, ..."]
    return ActionResult(False, f"Unknown action: '{action_name}'. Core actions: {list(ACTION_REGISTRY.keys())}", world_changed=False)
