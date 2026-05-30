"""
entities/base.py
Base Entity class and core entity types.
Designed for extensibility -- subclass Entity for anything that exists in the world.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum, auto
import uuid


class EntityType(Enum):
    MORIARTY = auto()
    PLAYER  = auto()    # Aaron, when he drops in
    NPC     = auto()
    ITEM    = auto()
    CREATURE= auto()
    MISC    = auto()


@dataclass
class Entity:
    """
    Base class for everything that exists in the world and has a position.
    """
    name: str
    entity_type: EntityType = EntityType.MISC
    x: int = 0
    y: int = 0
    symbol: str = "?"           # ASCII representation on map
    color: tuple = (160, 255, 160)
    blocks: bool = False        # Does this entity block tile passage?
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def describe(self) -> str:
        """Text description for perception prompts."""
        return f"{self.name} at ({self.x}, {self.y})"

    def move(self, dx: int, dy: int, world) -> bool:
        """
        Attempt to move by (dx, dy). Returns True if successful.
        Checks world passability.
        """
        nx, ny = self.x + dx, self.y + dy
        if world.is_passable(nx, ny):
            # Check no blocking entities at destination
            self.x = nx
            self.y = ny
            return True
        return False


# --- Direction helpers ---

DIRECTIONS = {
    "north": (0, -1),
    "south": (0, 1),
    "east":  (1, 0),
    "west":  (-1, 0),
    "ne":    (1, -1),
    "nw":    (-1, -1),
    "se":    (1, 1),
    "sw":    (-1, 1),
    "n": (0, -1),
    "s": (0, 1),
    "e": (1, 0),
    "w": (-1, 0),
}


# How many ticks between each hunger/fatigue increment.
# At ~1 tick/sec, HUNGER_RATE=10 means ~16 min from full to starving.
HUNGER_RATE  = 10
FATIGUE_RATE = 6


@dataclass
class StatusEffects:
    """Moriarty's current physiological/psychological state."""
    hunger: int = 50        # 0=starving, 100=full
    fatigue: int = 0        # 0=rested, 100=exhausted
    mood: str = "curious"   # freeform string -- LLM sets this
    _tick_n: int = field(default=0, repr=False, compare=False)

    def tick(self):
        """Advance one game tick."""
        self._tick_n += 1
        if self._tick_n % HUNGER_RATE == 0:
            self.hunger = max(0, self.hunger - 1)
        if self._tick_n % FATIGUE_RATE == 0:
            self.fatigue = min(100, self.fatigue + 1)

    def describe(self) -> str:
        hunger_desc = (
            "starving" if self.hunger < 10 else
            "very hungry" if self.hunger < 30 else
            "hungry" if self.hunger < 50 else
            "satisfied" if self.hunger < 80 else
            "full"
        )
        fatigue_desc = (
            "exhausted" if self.fatigue > 80 else
            "tired" if self.fatigue > 50 else
            "slightly tired" if self.fatigue > 30 else
            "rested"
        )
        return f"{hunger_desc}, {fatigue_desc}, feeling {self.mood}"


@dataclass
class MoriartyEntity(Entity):
    """
    Moriarty -- the primary AI-controlled character.
    Extends Entity with inventory and status.
    """
    inventory: list = field(default_factory=list)
    equipment: dict = field(default_factory=lambda: {
        "weapon": None, "offhand": None, "light": None,
        "head": None,   "body":   None,
    })
    status: StatusEffects = field(default_factory=StatusEffects)
    event_log: list = field(default_factory=list)
    max_log: int = 20
    hidden: bool = False   # set by hide action; cleared on movement

    def __post_init__(self):
        self.symbol = "N"
        self.color = (100, 255, 100)
        self.blocks = True

    def log_event(self, event: str):
        self.event_log.append(event)
        if len(self.event_log) > self.max_log:
            self.event_log.pop(0)

    def equip(self, item) -> str:
        slot = getattr(item, 'slot', '')
        if not getattr(item, 'equippable', False) or not slot:
            return f"The {item.name} can't be equipped."
        if slot not in self.equipment:
            return f"Unknown equipment slot: {slot}."
        current = self.equipment[slot]
        if current:
            self.inventory.append(current)
        if item in self.inventory:
            self.inventory.remove(item)
        self.equipment[slot] = item
        return f"Equipped {item.name}."

    def unequip(self, slot: str) -> str:
        if slot not in self.equipment:
            return f"No slot '{slot}'. Slots: {list(self.equipment.keys())}."
        item = self.equipment[slot]
        if not item:
            return f"Nothing equipped in {slot}."
        self.inventory.append(item)
        self.equipment[slot] = None
        return f"Unequipped {item.name}."

    def equipped_light_radius(self) -> int:
        light = self.equipment.get("light")
        return getattr(light, 'light_radius', 0) if light else 0

    def describe_inventory(self) -> str:
        if not self.inventory:
            return "nothing"
        return ", ".join(item.name for item in self.inventory)

    def describe_equipment(self) -> str:
        worn = {s: i for s, i in self.equipment.items() if i}
        if not worn:
            return "nothing equipped"
        return ", ".join(f"{s}: {i.name}" for s, i in worn.items())

    def describe(self) -> str:
        return f"Moriarty at ({self.x}, {self.y}) — {self.status.describe()}"
