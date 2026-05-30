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

        def sit_by_fire(actor, args, ws):
            if not self.lit:
                return ActionResult(False, "The fire is out — there's nothing warm to sit by.",
                                    world_changed=False)
            actor.status.fatigue = max(0, actor.status.fatigue - 12)
            actor.status.mood = "calm"
            return ActionResult(True,
                "You sit close to the fire. The heat soaks in and the world quiets down.")

        result = {
            "examine": lambda a, args, ws: ActionResult(True, self.describe(), world_changed=False),
            "warm":    warm,
            "sit":     sit_by_fire,
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

        def climb(actor, args, ws):
            actor.status.fatigue = min(100, actor.status.fatigue + 3)
            # Build a brief elevated view description
            from ..world.state import _dist, _direction_name
            from ..world.tiles import TileType
            terrain_seen = {}
            for dy in range(-20, 21):
                for dx in range(-20, 21):
                    if _dist(dx, dy) > 20:
                        continue
                    tile = ws.world.get(actor.x + dx, actor.y + dy)
                    if tile:
                        t = tile.tile_type.name
                        d = _direction_name(dx, dy)
                        terrain_seen.setdefault(t, set()).add(d)
            lines = []
            for t, dirs in sorted(terrain_seen.items()):
                lines.append(f"  {t.lower()}: {', '.join(sorted(dirs)[:3])}")
            view = "\n".join(lines[:8])
            return ActionResult(True,
                f"You scramble up the boulder and stand on top.\nFrom here you can see:\n{view}",
                world_changed=False)

        def hide(actor, args, ws):
            actor.hidden = True
            return ActionResult(True,
                "You press yourself against the boulder. Anyone passing may not see you.",
                world_changed=False)

        def sit(actor, args, ws):
            actor.status.fatigue = max(0, actor.status.fatigue - 3)
            return ActionResult(True,
                "You sit against the boulder. The stone is cold and hard but the rest is welcome.",
                world_changed=False)

        return {
            "examine": lambda a, args, ws: ActionResult(
                True, f"{self.name}: {self.description}. Solid, immovable, ancient.",
                world_changed=False),
            "shelter": lambda a, args, ws: ActionResult(
                True, "You crouch in the lee of the boulder. The wind drops away.",
                world_changed=False),
            "climb":  climb,
            "hide":   hide,
            "sit":    sit,
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

        def sit(actor, args, ws):
            actor.status.fatigue = max(0, actor.status.fatigue - 6)
            return ActionResult(True,
                "You sit on the log. The bark is rough but the rest is real — fatigue eases.",
                world_changed=False)

        def chop(actor, args, ws):
            has_tool = any(i.name.lower() in ("stick", "axe") for i in actor.inventory)
            if not has_tool:
                return ActionResult(False,
                    "You'd need something to chop with — a stick or an axe.",
                    world_changed=False)
            from ..entities.items import make_firewood
            firewood = make_firewood(actor.x, actor.y)
            actor.inventory.append(firewood)
            actor.status.fatigue = min(100, actor.status.fatigue + 10)
            self.description = "a split log, mostly chopped"
            self.color = (70, 45, 20)
            return ActionResult(True,
                "You work at the log with your stick. It splits roughly — not great firewood, but it'll burn.")

        def hide(actor, args, ws):
            actor.hidden = True
            return ActionResult(True,
                "You crouch behind the fallen log. The forest holds you in its shadow.",
                world_changed=False)

        return {
            "examine": lambda a, args, ws: ActionResult(
                True, f"{self.name}: {self.description}. Bark peeling, soft with rot.",
                world_changed=False),
            "sit":         sit,
            "investigate": lambda a, args, ws: ActionResult(
                True, "You peer under the log — beetles, damp soil, a smell of deep earth.",
                world_changed=False),
            "chop":        chop,
            "hide":        hide,
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
