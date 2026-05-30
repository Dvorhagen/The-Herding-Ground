"""
world/objects.py
WorldObject: stationary, interactive world objects (campfires, chests, etc.)
These sit between passive tiles and mobile entities — they occupy a tile position
and expose an interactions() dict, but they never move. The map editor can place
and remove them.

Interaction handlers share the action handler signature:
    handler(actor, args: dict, world_state) -> ActionResult
"""

from dataclasses import dataclass, field
from typing import Callable
import uuid


@dataclass
class WorldObject:
    name: str
    x: int
    y: int
    symbol: str = "O"
    color: tuple = (160, 255, 160)
    blocks: bool = False
    opacity: float = 0.0
    description: str = "an object"
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def interactions(self) -> dict[str, Callable]:
        """Return {verb: handler(actor, args, world_state) -> ActionResult}."""
        return {}

    def describe(self) -> str:
        verbs = list(self.interactions().keys())
        verb_str = f" [{', '.join(verbs)}]" if verbs else ""
        return f"{self.name}: {self.description}{verb_str}"


@dataclass
class Campfire(WorldObject):
    lit: bool = True

    def __post_init__(self):
        self.symbol = "*"
        self.color = (220, 120, 40)
        self.description = "a crackling campfire" if self.lit else "a cold ash pile"

    def interactions(self) -> dict:
        from ..entities.actions import ActionResult

        def warm(actor, args, world_state):
            if not self.lit:
                return ActionResult(False, "The campfire is out — nothing to warm yourself at.", world_changed=False)
            actor.status.fatigue = max(0, actor.status.fatigue - 20)
            actor.status.mood = "warm and rested"
            return ActionResult(True, "You warm yourself at the campfire. The fatigue eases.")

        def extinguish(actor, args, world_state):
            if not self.lit:
                return ActionResult(False, "The campfire is already out.", world_changed=False)
            self.lit = False
            self.color = (60, 50, 40)
            self.description = "a cold ash pile"
            return ActionResult(True, "You extinguish the campfire.")

        def light(actor, args, world_state):
            if self.lit:
                return ActionResult(False, "The campfire is already burning.", world_changed=False)
            self.lit = True
            self.color = (220, 120, 40)
            self.description = "a crackling campfire"
            return ActionResult(True, "You light the campfire. It crackles to life.")

        result = {
            "examine": lambda a, args, ws: ActionResult(True, self.describe(), world_changed=False),
            "warm":    warm,
        }
        if self.lit:
            result["extinguish"] = extinguish
        else:
            result["light"] = light
        return result


@dataclass
class Chest(WorldObject):
    contents: list = field(default_factory=list)
    locked: bool = False

    def __post_init__(self):
        self.symbol = "="
        self.color = (160, 120, 40)
        self.blocks = True
        self.description = "a wooden chest"

    def interactions(self) -> dict:
        from ..entities.actions import ActionResult

        def open_chest(actor, args, world_state):
            if self.locked:
                return ActionResult(False, "The chest is locked.", world_changed=False)
            if not self.contents:
                return ActionResult(True, "The chest is empty.", world_changed=False)
            names = ", ".join(i.name for i in self.contents)
            return ActionResult(True, f"The chest contains: {names}.", world_changed=False)

        def take_from_chest(actor, args, world_state):
            if self.locked:
                return ActionResult(False, "The chest is locked.", world_changed=False)
            if not self.contents:
                return ActionResult(False, "The chest is empty.", world_changed=False)
            target = args.get("item_name", "").lower()
            if target:
                item = next((i for i in self.contents if i.name.lower() == target), None)
                if not item:
                    names = ", ".join(i.name for i in self.contents)
                    return ActionResult(False, f"No '{target}' in chest. Contains: {names}.", world_changed=False)
            else:
                item = self.contents[0]
            self.contents.remove(item)
            item.x, item.y = actor.x, actor.y
            actor.inventory.append(item)
            return ActionResult(True, f"Took {item.name} from the chest.")

        return {
            "examine": lambda a, args, ws: ActionResult(True, self.describe(), world_changed=False),
            "open":    open_chest,
            "take":    take_from_chest,
        }

    def describe(self) -> str:
        lock_str = " (locked)" if self.locked else ""
        if self.contents and not self.locked:
            names = ", ".join(i.name for i in self.contents)
            contents_str = f" Contains: {names}."
        else:
            contents_str = ""
        return f"{self.name}: {self.description}{lock_str}.{contents_str}"


@dataclass
class Boulder(WorldObject):
    def __post_init__(self):
        self.symbol = "O"
        self.color = (80, 85, 70)
        self.blocks = True
        self.opacity = 0.4
        self.description = "a large mossy boulder"

    def interactions(self) -> dict:
        from ..entities.actions import ActionResult
        return {
            "examine": lambda a, args, ws: ActionResult(
                True, f"{self.name}: {self.description}. Solid, immovable, ancient.",
                world_changed=False),
            "shelter": lambda a, args, ws: ActionResult(
                True, "You crouch in the shadow of the boulder. The wind drops away.",
                world_changed=False),
        }


@dataclass
class FallenLog(WorldObject):
    def __post_init__(self):
        self.symbol = "="
        self.color = (90, 60, 30)
        self.blocks = False
        self.description = "a mossy fallen log"

    def interactions(self) -> dict:
        from ..entities.actions import ActionResult
        return {
            "examine": lambda a, args, ws: ActionResult(
                True, f"{self.name}: {self.description}. Bark peeling, soft with rot.",
                world_changed=False),
            "sit": lambda a, args, ws: ActionResult(
                True, "You sit on the log for a moment. The forest is quiet around you.",
                world_changed=False),
            "investigate": lambda a, args, ws: ActionResult(
                True, "You peer under the log — beetles, damp soil, a smell of deep earth.",
                world_changed=False),
        }


@dataclass
class Bush(WorldObject):
    foraged: bool = False

    def __post_init__(self):
        self.symbol = "&"
        self.color = (40, 130, 50)
        self.blocks = False
        self.description = "a dense berry-laden shrub"

    def interactions(self) -> dict:
        from ..entities.actions import ActionResult
        from ..entities.items import make_berries

        def forage(actor, args, world_state):
            if self.foraged:
                return ActionResult(False,
                    "The bush is already stripped bare — just leaves and thorns.",
                    world_changed=False)
            self.foraged = True
            self.color = (30, 90, 35)
            self.description = "a stripped shrub, thorny and bare"
            berries = make_berries(actor.x, actor.y)
            actor.inventory.append(berries)
            return ActionResult(True,
                "You pick through the thorns and gather a handful of wild berries.")

        return {
            "examine": lambda a, args, ws: ActionResult(
                True,
                (f"{self.name}: {self.description}." if self.foraged
                 else f"{self.name}: {self.description}. Dark berries cluster among the thorns."),
                world_changed=False),
            "forage": forage,
        }


@dataclass
class WildMushroom(WorldObject):
    def __post_init__(self):
        self.symbol = "m"
        self.color = (150, 120, 50)
        self.blocks = False
        self.description = "a cluster of wild mushrooms"

    def interactions(self) -> dict:
        from ..entities.actions import ActionResult
        from ..entities.items import make_mushroom_item

        def pick(actor, args, world_state):
            world_state.remove_object(self)
            mushroom = make_mushroom_item(actor.x, actor.y)
            actor.inventory.append(mushroom)
            return ActionResult(True,
                "You twist the mushrooms free at the base. They smell rich and earthy.")

        return {
            "examine": lambda a, args, ws: ActionResult(
                True,
                f"{self.name}: {self.description}. Brown-capped, gills pale underneath. Probably edible.",
                world_changed=False),
            "pick": pick,
        }


@dataclass
class FlowerPatch(WorldObject):
    picked: bool = False

    def __post_init__(self):
        self.symbol = "'"
        self.color = (180, 210, 90)
        self.blocks = False
        self.description = "a scatter of wildflowers"

    def interactions(self) -> dict:
        from ..entities.actions import ActionResult

        def pick_flowers(actor, args, world_state):
            if self.picked:
                return ActionResult(False,
                    "You already picked these — just stems remain.", world_changed=False)
            self.picked = True
            self.color = (100, 120, 60)
            self.description = "bare flower stems"
            actor.status.mood = "calm"
            return ActionResult(True,
                "You gather a handful of wildflowers. Their scent is bright and clean.")

        return {
            "examine": lambda a, args, ws: ActionResult(
                True,
                (f"{self.name}: {self.description}." if self.picked
                 else f"{self.name}: {self.description}. Yellow and white, nodding in the breeze."),
                world_changed=False),
            "pick": pick_flowers,
            "smell": lambda a, args, ws: ActionResult(
                True, "You lean close. The scent is clean and faintly sweet.",
                world_changed=False),
        }


# --- Factory functions ---

def make_campfire(x: int, y: int) -> Campfire:
    return Campfire(name="campfire", x=x, y=y)

def make_chest(x: int, y: int, contents=None, locked=False) -> Chest:
    return Chest(name="chest", x=x, y=y, contents=contents or [], locked=locked)

def make_boulder(x: int, y: int) -> Boulder:
    return Boulder(name="boulder", x=x, y=y)

def make_fallen_log(x: int, y: int) -> FallenLog:
    return FallenLog(name="fallen log", x=x, y=y)

def make_bush(x: int, y: int) -> Bush:
    return Bush(name="bush", x=x, y=y)

def make_wild_mushroom(x: int, y: int) -> WildMushroom:
    return WildMushroom(name="mushrooms", x=x, y=y)

def make_flower_patch(x: int, y: int) -> FlowerPatch:
    return FlowerPatch(name="wildflowers", x=x, y=y)
