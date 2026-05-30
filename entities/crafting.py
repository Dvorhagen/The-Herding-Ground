"""
entities/crafting.py
Recipe registry and helpers for the craft action.

To add a recipe: add an entry to RECIPES. inputs is a dict of
{item_name: quantity}. output is a factory function(x, y) -> Item.
"""

from .items import (
    make_stone_knife, make_spear, make_club, make_torch, make_rope,
    make_bandage,
)


RECIPES: dict[str, dict] = {
    "stone knife": {
        "description": "Sharp flint blade on a stick handle — weapon and field tool",
        "inputs": {"stone": 1, "stick": 1},
        "output": make_stone_knife,
    },
    "spear": {
        "description": "Long shaft with a flint tip — reach weapon, good for hunting",
        "inputs": {"stick": 1, "flint": 1, "rope": 1},
        "output": make_spear,
    },
    "club": {
        "description": "Heavy knotted branch — slow but hard-hitting",
        "inputs": {"stick": 2},
        "output": make_club,
    },
    "torch": {
        "description": "Stick wrapped with burning material — illuminates nearby area",
        "inputs": {"stick": 1, "firewood": 1},
        "output": make_torch,
    },
    "rope": {
        "description": "Twisted reed cordage — enables spear crafting",
        "inputs": {"reed": 3},
        "output": make_rope,
    },
    "bandage": {
        "description": "Bark-strip wound dressing — stops bleeding when applied",
        "inputs": {"bark strip": 2},
        "output": make_bandage,
    },
}


def inventory_counts(inventory: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in inventory:
        counts[item.name.lower()] = counts.get(item.name.lower(), 0) + 1
    return counts


def can_craft(inventory: list, recipe: dict) -> tuple[bool, str]:
    counts = inventory_counts(inventory)
    missing = []
    for item_name, qty in recipe["inputs"].items():
        have = counts.get(item_name, 0)
        if have < qty:
            missing.append(f"{qty - have}× {item_name}")
    if missing:
        return False, "Missing: " + ", ".join(missing)
    return True, "ok"


def consume_inputs(inventory: list, recipe: dict):
    """Remove recipe inputs from inventory in-place."""
    needed = dict(recipe["inputs"])
    to_remove = []
    for item in inventory:
        name = item.name.lower()
        if needed.get(name, 0) > 0:
            to_remove.append(item)
            needed[name] -= 1
    for item in to_remove:
        inventory.remove(item)
