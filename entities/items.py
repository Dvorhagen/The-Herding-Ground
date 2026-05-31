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
    blocks: bool = False
    # Equipment fields — only meaningful when equippable=True
    equippable: bool = False
    slot: str = ""          # "weapon", "offhand", "light", "head", "body"
    damage: int = 0         # weapon damage
    light_radius: int = 0   # tiles of extra vision when equipped
    consumed_on_use: bool = False   # non-food items that are used up

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

def make_firewood(x: int, y: int) -> Item:
    item = Item(
        name="firewood", x=x, y=y,
        item_type=ItemType.MATERIAL,
        description="a rough bundle of split wood, good for burning",
        weight=1.5,
        symbol="f", color=(100, 70, 30)
    )
    return item

def make_stone(x: int, y: int) -> Item:
    return Item(
        name="stone", x=x, y=y,
        item_type=ItemType.MATERIAL,
        description="a smooth, palm-sized river stone",
        weight=0.5, symbol="*", color=(100, 100, 90)
    )


# --- Natural materials ---

def make_reed(x: int, y: int) -> Item:
    return Item(
        name="reed", x=x, y=y,
        item_type=ItemType.MATERIAL,
        description="a long fibrous reed stem, good for weaving",
        weight=0.2, symbol="|", color=(80, 120, 60)
    )

def make_rope(x: int, y: int) -> Item:
    return Item(
        name="rope", x=x, y=y,
        item_type=ItemType.MATERIAL,
        description="a length of twisted reed rope, surprisingly strong",
        weight=0.5, symbol="~", color=(120, 100, 60)
    )

def make_flint(x: int, y: int) -> Item:
    return Item(
        name="flint", x=x, y=y,
        item_type=ItemType.MATERIAL,
        description="a sharp-edged flint nodule",
        weight=0.4, symbol="^", color=(80, 80, 90)
    )

def make_feather(x: int, y: int) -> Item:
    return Item(
        name="feather", x=x, y=y,
        item_type=ItemType.MATERIAL,
        description="a long flight feather, still clean",
        weight=0.05, symbol='"', color=(180, 180, 160)
    )

def make_egg(x: int, y: int) -> FoodItem:
    return FoodItem(
        name="egg", x=x, y=y,
        description="a small speckled egg",
        nutrition=10, symbol="o", color=(200, 180, 120)
    )

def make_meat(x: int, y: int) -> FoodItem:
    return FoodItem(
        name="raw meat", x=x, y=y,
        description="a chunk of raw animal meat — should be cooked eventually",
        nutrition=25, symbol="%", color=(180, 60, 60)
    )


# --- Weapons (equippable) ---

def make_stone_knife(x: int, y: int) -> ToolItem:
    item = ToolItem(
        name="stone knife", x=x, y=y,
        description="a crude but effective flint blade lashed to a short handle",
        symbol="k", color=(120, 120, 110)
    )
    item.equippable = True
    item.slot = "weapon"
    item.damage = 5
    return item

def make_spear(x: int, y: int) -> ToolItem:
    item = ToolItem(
        name="spear", x=x, y=y,
        description="a straight shaft with a sharpened flint tip — good reach",
        symbol="!", color=(130, 100, 50)
    )
    item.equippable = True
    item.slot = "weapon"
    item.damage = 8
    return item

def make_club(x: int, y: int) -> ToolItem:
    item = ToolItem(
        name="club", x=x, y=y,
        description="a heavy knotted branch — blunt and brutal",
        symbol=")", color=(100, 70, 30)
    )
    item.equippable = True
    item.slot = "weapon"
    item.damage = 6
    return item


# --- Light sources (equippable) ---

def make_bark_strip(x: int, y: int) -> Item:
    return Item(
        name="bark strip", x=x, y=y,
        item_type=ItemType.MATERIAL,
        description="a strip of dry inner bark, fibrous and absorbent",
        weight=0.1, symbol="-", color=(110, 80, 40)
    )


def make_bandage(x: int, y: int) -> Item:
    item = Item(
        name="bandage", x=x, y=y,
        item_type=ItemType.MATERIAL,
        description="strips of bark bound together — rough but effective",
        weight=0.1, usable=True, consumed_on_use=True,
        symbol="+", color=(180, 160, 120)
    )
    def _use(user, world):
        return user.combat_state.apply_bandage_to_worst()
    item.on_use = _use
    return item


def make_healing_herb_item(x: int, y: int) -> Item:
    item = Item(
        name="healing herb", x=x, y=y,
        item_type=ItemType.MATERIAL,
        description="a cluster of medicinal leaves — antiseptic, promotes healing",
        weight=0.05, usable=True, consumed_on_use=True,
        symbol="'", color=(80, 180, 80)
    )
    def _use(user, world):
        return user.combat_state.apply_herb_to_worst()
    item.on_use = _use
    return item


@dataclass
class ClothingItem(Item):
    """Wearable clothing occupying a body-related slot."""
    def __post_init__(self):
        self.item_type = ItemType.MISC
        self.equippable = True
        super().__post_init__()
        self.symbol = "="


def make_worn_tunic(x: int = 0, y: int = 0) -> ClothingItem:
    item = ClothingItem(name="worn tunic", x=x, y=y,
                        description="a faded linen tunic, soft with long wear",
                        weight=0.3, color=(100, 80, 60))
    item.slot = "body"
    return item

def make_rough_trousers(x: int = 0, y: int = 0) -> ClothingItem:
    item = ClothingItem(name="rough trousers", x=x, y=y,
                        description="coarse cloth trousers, functional if plain",
                        weight=0.2, color=(80, 70, 50))
    item.slot = "legs"
    return item

def make_simple_boots(x: int = 0, y: int = 0) -> ClothingItem:
    item = ClothingItem(name="simple boots", x=x, y=y,
                        description="worn leather boots, fitted and broken in",
                        weight=0.4, color=(70, 50, 30))
    item.slot = "feet"
    return item

def make_small_satchel(x: int = 0, y: int = 0) -> Item:
    item = Item(name="small satchel", x=x, y=y,
                item_type=ItemType.MISC,
                description="a leather satchel hung at the hip — holds more",
                weight=0.2, symbol="s", color=(110, 75, 40))
    item.equippable = True
    item.slot = "back"
    return item


def make_torch(x: int, y: int) -> ToolItem:
    item = ToolItem(
        name="torch", x=x, y=y,
        description="a stick wrapped with burning material — warm light, limited life",
        symbol="†", color=(220, 150, 40)
    )
    item.equippable = True
    item.slot = "light"
    item.light_radius = 8
    return item
