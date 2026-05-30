"""
entities/items.py
Item classes. All items extend Entity with use/pickup/drop behavior.
Extend ItemType and create subclasses for new item categories.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from .base import Entity, EntityType


class ItemType(Enum):
    FOOD      = auto()
    TOOL      = auto()
    MATERIAL  = auto()
    ARTIFACT  = auto()    # Special/story items
    MISC      = auto()


@dataclass
class Item(Entity):
    """Base item class. All items can be picked up and dropped."""
    item_type: ItemType = ItemType.MISC
    weight: float = 1.0
    description: str = "an unremarkable object"
    usable: bool = False
    blocks: bool = False    # Items don't block movement by default

    def __post_init__(self):
        self.entity_type = EntityType.ITEM
        self.symbol = "i"

    def on_use(self, user, world) -> str:
        """Override in subclasses. Returns a text description of what happened."""
        return f"You use the {self.name}, but nothing happens."

    def interactions(self) -> dict:
        """Return {verb: handler(actor, args, world_state) -> ActionResult}.
        Usable items expose 'use'; all items expose 'examine'."""
        from .actions import ActionResult
        result = {
            "examine": lambda actor, args, ws: ActionResult(True, self.describe(), world_changed=False),
        }
        if self.usable:
            item = self
            def use_handler(actor, args, world_state):
                msg = item.on_use(actor, world_state)
                if item.item_type.name == 'FOOD' and item in actor.inventory:
                    actor.inventory.remove(item)
                return ActionResult(True, msg)
            result["use"] = use_handler
        return result

    def describe(self) -> str:
        return f"{self.name}: {self.description}"


@dataclass
class FoodItem(Item):
    """Edible items that restore hunger."""
    nutrition: int = 20

    def __post_init__(self):
        self.item_type = ItemType.FOOD
        self.usable = True
        super().__post_init__()
        self.symbol = "%"

    def on_use(self, user, world) -> str:
        user.status.hunger = min(100, user.status.hunger + self.nutrition)
        return f"You eat the {self.name}. It tastes {self.description}."


@dataclass
class ToolItem(Item):
    """Tools with specific uses."""

    def __post_init__(self):
        self.item_type = ItemType.TOOL
        self.usable = True
        super().__post_init__()
        self.symbol = "/"


# --- Starter world items ---

def make_apple(x: int, y: int) -> FoodItem:
    return FoodItem(
        name="apple", x=x, y=y,
        description="sweet and slightly tart",
        nutrition=15, symbol="a", color=(180, 60, 60)
    )

def make_stick(x: int, y: int) -> ToolItem:
    return ToolItem(
        name="stick", x=x, y=y,
        description="a sturdy fallen branch",
        symbol="/", color=(120, 80, 40)
    )


# --- Natural world items ---

def make_berries(x: int, y: int) -> FoodItem:
    return FoodItem(
        name="berries", x=x, y=y,
        description="tart wild berries, staining your fingers purple",
        nutrition=8, symbol="o", color=(120, 40, 120)
    )

def make_mushroom_item(x: int, y: int) -> FoodItem:
    return FoodItem(
        name="mushroom", x=x, y=y,
        description="a dense, earthy-smelling fungus",
        nutrition=12, symbol="m", color=(160, 130, 60)
    )

def make_stone(x: int, y: int) -> Item:
    item = Item(
        name="stone", x=x, y=y,
        item_type=ItemType.MATERIAL,
        description="a smooth, palm-sized river stone",
        weight=0.5,
        symbol="*", color=(100, 100, 90)
    )
    return item
