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
