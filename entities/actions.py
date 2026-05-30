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


def action_reflect(actor, args: dict, world_state) -> ActionResult:
    """
    Special action: Moriarty pauses to reflect on its state.
    This will trigger a memory-write check.
    """
    return ActionResult(True, "REFLECT", world_changed=False, data={"trigger_reflection": True})


# Registry maps action name strings (from LLM output) to handler functions
ACTION_REGISTRY = {
    "move":    action_move,
    "go":      action_move,     # alias
    "walk":    action_move,     # alias
    "pickup":  action_pickup,
    "pick up": action_pickup,
    # "take" is intentionally absent — it resolves dynamically against world objects
    # (e.g. chest.take). Use "pickup" or "pick up" for items on the ground.
    "drop":    action_drop,
    "use":     action_use,
    "eat":     action_use,      # alias (item_name required)
    "examine": action_examine,
    "look":    action_examine,  # alias
    "wait":    action_wait,
    "rest":    action_wait,     # alias
    "reflect": action_reflect,
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
