"""
world/save.py
Persistent world state serialization / deserialization.

Format: JSON with RLE tile compression (~1-2 MB for 512×512 world).
Save path: moriarty/save/world.json

What is saved:
  - Tile grid (RLE encoded)
  - World objects with full state (lit, foraged, contents, etc.)
  - Ground entities: items and animals
  - Moriarty: position, inventory, equipment, combat state, status, event log
  - conversation_log, tick count

What is NOT saved:
  - visible_tiles — recomputed from world geometry each tick
  - Player entity (PlayerEntity) — figure disappears on quit, reasonable
  - Grapple reference — cross-object reference can't survive serialisation;
    grapple is cleared on load

Wiki memory (memory/wiki/) persists independently as markdown files and
requires no special handling here.
"""

import json
import gzip
from datetime import datetime
from pathlib import Path

from .tiles import WorldMap, TileType
from .state import WorldState
from ..entities.base import MoriartyEntity, EntityType
from ..entities.items import (
    make_apple, make_stick, make_berries, make_mushroom_item, make_firewood,
    make_stone, make_bark_strip, make_bandage, make_healing_herb_item,
    make_reed, make_rope, make_flint, make_feather, make_egg, make_meat,
    make_stone_knife, make_spear, make_club, make_torch, Item, ItemType,
)
from ..entities.animals import make_rabbit, make_deer, make_fox, make_bird
from ..entities.combat import (
    CombatState, Wound, BodyPart, WoundSeverity,
)

SAVE_VERSION = 2


# ── Item registry ─────────────────────────────────────────────────────────────

_ITEM_FACTORIES = {
    "apple":        make_apple,
    "stick":        make_stick,
    "berries":      make_berries,
    "mushroom":     make_mushroom_item,
    "firewood":     make_firewood,
    "stone":        make_stone,
    "bark strip":   make_bark_strip,
    "bandage":      make_bandage,
    "healing herb": make_healing_herb_item,
    "reed":         make_reed,
    "rope":         make_rope,
    "flint":        make_flint,
    "feather":      make_feather,
    "egg":          make_egg,
    "raw meat":     make_meat,
    "stone knife":  make_stone_knife,
    "spear":        make_spear,
    "club":         make_club,
    "torch":        make_torch,
}

_ANIMAL_FACTORIES = {
    "rabbit": make_rabbit,
    "deer":   make_deer,
    "fox":    make_fox,
    "bird":   make_bird,
}


# ── Tile RLE ──────────────────────────────────────────────────────────────────

def _encode_tiles(world: WorldMap) -> list:
    """Run-length encode the tile grid (row-major order)."""
    runs = []
    current = None
    count = 0
    for y in range(world.height):
        for x in range(world.width):
            tile = world.get(x, y)
            name = tile.tile_type.name if tile else "GRASS"
            if name == current:
                count += 1
            else:
                if current is not None:
                    runs.append([current, count])
                current = name
                count = 1
    if current is not None:
        runs.append([current, count])
    return runs


def _decode_tiles(world: WorldMap, runs: list):
    """Decode RLE runs back into the world grid."""
    idx = 0
    for tname, count in runs:
        tile_enum = TileType[tname]
        for _ in range(count):
            x = idx % world.width
            y = idx // world.width
            world.set(x, y, tile_enum)
            idx += 1


# ── Item serialization ────────────────────────────────────────────────────────

def _ser_item(item) -> dict | None:
    if item is None:
        return None
    return {"item_name": item.name, "x": item.x, "y": item.y}


def _de_item(data: dict | None, fallback_xy=(0, 0)):
    if data is None:
        return None
    name = data.get("item_name", "")
    x, y = data.get("x", fallback_xy[0]), data.get("y", fallback_xy[1])
    factory = _ITEM_FACTORIES.get(name)
    if factory:
        return factory(x, y)
    # Unknown item — create a generic placeholder
    item = Item(name=name, x=x, y=y)
    return item


# ── WorldObject serialization ─────────────────────────────────────────────────

def _ser_world_object(obj) -> dict:
    d = {
        "type": type(obj).__name__,
        "name": obj.name,
        "x":    obj.x,
        "y":    obj.y,
    }
    if hasattr(obj, "lit"):       d["lit"]       = obj.lit
    if hasattr(obj, "locked"):    d["locked"]    = obj.locked
    if hasattr(obj, "foraged"):   d["foraged"]   = obj.foraged
    if hasattr(obj, "harvested"): d["harvested"] = obj.harvested
    if hasattr(obj, "picked"):    d["picked"]    = obj.picked
    if hasattr(obj, "has_nest"):  d["has_nest"]  = obj.has_nest
    if hasattr(obj, "contents"):
        d["contents"] = [_ser_item(i) for i in obj.contents]
    return d


def _de_world_object(data: dict):
    from .objects import (
        Campfire, Chest, Boulder, FallenLog, Bush, WildMushroom, FlowerPatch,
        Tree, HollowTree, ReedBed, HerbPatch,
    )
    t     = data["type"]
    name  = data.get("name", t.lower())
    x, y  = data["x"], data["y"]

    if t == "Campfire":
        obj = Campfire(name=name, x=x, y=y)
        obj.lit = data.get("lit", True)
        if not obj.lit:
            obj.color = (60, 50, 40)
            obj.description = "a cold ash pile"
    elif t == "Chest":
        contents = [_de_item(i, (x, y)) for i in data.get("contents", [])]
        contents = [c for c in contents if c is not None]
        obj = Chest(name=name, x=x, y=y, contents=contents,
                    locked=data.get("locked", False))
    elif t == "Boulder":
        obj = Boulder(name=name, x=x, y=y)
    elif t == "FallenLog":
        obj = FallenLog(name=name, x=x, y=y)
    elif t == "Bush":
        obj = Bush(name=name, x=x, y=y, foraged=data.get("foraged", False))
        if obj.foraged:
            obj.color = (30, 90, 35)
            obj.description = "a stripped shrub, thorny and bare"
    elif t == "WildMushroom":
        obj = WildMushroom(name=name, x=x, y=y)
    elif t == "FlowerPatch":
        obj = FlowerPatch(name=name, x=x, y=y, picked=data.get("picked", False))
        if obj.picked:
            obj.color = (100, 120, 60)
            obj.description = "bare flower stems"
    elif t == "Tree":
        obj = Tree(name=name, x=x, y=y, has_nest=data.get("has_nest", False))
    elif t == "HollowTree":
        obj = HollowTree(name=name, x=x, y=y)
    elif t == "ReedBed":
        obj = ReedBed(name=name, x=x, y=y, harvested=data.get("harvested", False))
        if obj.harvested:
            obj.color = (40, 70, 45)
            obj.description = "a cut reed stand, stubble at the waterline"
    elif t == "HerbPatch":
        obj = HerbPatch(name=name, x=x, y=y, harvested=data.get("harvested", False))
        if obj.harvested:
            obj.color = (40, 100, 50)
            obj.description = "a stripped herb patch, stalks bent and bare"
    else:
        from .objects import WorldObject
        obj = WorldObject(name=name, x=x, y=y)
    return obj


# ── Animal serialization ──────────────────────────────────────────────────────

def _ser_animal(animal) -> dict:
    return {
        "species": animal.species,
        "name":    animal.name,
        "x":       animal.x,
        "y":       animal.y,
        "health":  animal.health,
        "alive":   animal.alive,
    }


def _de_animal(data: dict):
    species = data.get("species", "animal")
    factory = _ANIMAL_FACTORIES.get(species)
    if not factory:
        return None
    animal = factory(data["x"], data["y"])
    animal.health = data.get("health", animal.max_health)
    animal.alive  = data.get("alive", True)
    return animal


# ── Combat state serialization ────────────────────────────────────────────────

def _ser_wound(w: Wound) -> dict:
    return {
        "part":          w.part.value,
        "severity":      w.severity.name,
        "age":           w.age,
        "bandaged":      w.bandaged,
        "infected":      w.infected,
        "herb_ticks":    w.herb_ticks,
        "heal_progress": w.heal_progress,
    }


def _de_wound(d: dict) -> Wound:
    part     = next(p for p in BodyPart if p.value == d["part"])
    severity = WoundSeverity[d["severity"]]
    return Wound(
        part=part, severity=severity,
        age=d.get("age", 0),
        bandaged=d.get("bandaged", False),
        infected=d.get("infected", False),
        herb_ticks=d.get("herb_ticks", 0),
        heal_progress=d.get("heal_progress", 0),
    )


def _ser_combat_state(cs: CombatState) -> dict:
    return {
        "wounds":     [_ser_wound(w) for w in cs.wounds],
        "blood_loss": cs.blood_loss,
        "shock":      cs.shock,
    }


def _de_combat_state(d: dict) -> CombatState:
    cs = CombatState()
    cs.wounds     = [_de_wound(w) for w in d.get("wounds", [])]
    cs.blood_loss = d.get("blood_loss", 0)
    cs.shock      = d.get("shock", 0)
    return cs


# ── Moriarty serialization ────────────────────────────────────────────────────

def _ser_moriarty(mo: MoriartyEntity) -> dict:
    equipment = {}
    for slot, item in mo.equipment.items():
        equipment[slot] = _ser_item(item)
    return {
        "x":            mo.x,
        "y":            mo.y,
        "hidden":       mo.hidden,
        "is_resting":   mo.is_resting,
        "status": {
            "hunger":   mo.status.hunger,
            "fatigue":  mo.status.fatigue,
            "mood":     mo.status.mood,
            "_tick_n":  mo.status._tick_n,
        },
        "inventory":    [_ser_item(i) for i in mo.inventory],
        "equipment":    equipment,
        "combat_state": _ser_combat_state(mo.combat_state),
        "event_log":    list(mo.event_log),
        "max_log":      mo.max_log,
    }


def _de_moriarty(d: dict) -> MoriartyEntity:
    mo = MoriartyEntity(
        name="Moriarty",
        entity_type=EntityType.MORIARTY,
        x=d["x"], y=d["y"],
    )
    mo.hidden     = d.get("hidden", False)
    mo.is_resting = d.get("is_resting", False)
    mo.max_log    = d.get("max_log", 20)
    mo.event_log  = list(d.get("event_log", []))

    s = d.get("status", {})
    mo.status.hunger   = s.get("hunger", 50)
    mo.status.fatigue  = s.get("fatigue", 0)
    mo.status.mood     = s.get("mood", "curious")
    mo.status._tick_n  = s.get("_tick_n", 0)

    mo.inventory = [_de_item(i, (mo.x, mo.y))
                    for i in d.get("inventory", [])]
    mo.inventory = [i for i in mo.inventory if i is not None]

    eq_data = d.get("equipment", {})
    for slot in mo.equipment:
        mo.equipment[slot] = _de_item(eq_data.get(slot), (mo.x, mo.y))

    mo.combat_state = _de_combat_state(d.get("combat_state", {}))
    return mo


# ── Public API ────────────────────────────────────────────────────────────────

def save_world(world_state: WorldState, path: Path | str):
    """Serialise WorldState to JSON at path. Creates parent dirs as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    from ..entities.animals import Animal
    from ..entities.items import Item

    entities_data = []
    for e in world_state.entities:
        if isinstance(e, Animal):
            entities_data.append({"kind": "animal", **_ser_animal(e)})
        elif isinstance(e, Item):
            d = _ser_item(e)
            if d:
                entities_data.append({"kind": "item", **d})

    payload = {
        "version":    SAVE_VERSION,
        "saved_at":   datetime.now().isoformat(timespec="seconds"),
        "tick":       world_state.tick,
        "world": {
            "width":  world_state.world.width,
            "height": world_state.world.height,
            "tiles":  _encode_tiles(world_state.world),
        },
        "world_objects":    [_ser_world_object(o) for o in world_state.world_objects],
        "entities":         entities_data,
        "moriarty":         _ser_moriarty(world_state.moriarty),
        "conversation_log": getattr(world_state, "conversation_log", []),
    }

    path.write_text(json.dumps(payload, indent=2))
    print(f"[SAVE] World saved to {path}  (tick {world_state.tick})")


def load_world(path: Path | str) -> WorldState:
    """Deserialise a saved WorldState from path. Raises FileNotFoundError if missing."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No save file at {path}")

    payload = json.loads(path.read_text())
    v = payload.get("version", 1)
    if v > SAVE_VERSION:
        print(f"[WARN] Save version {v} is newer than supported {SAVE_VERSION}; loading anyway")

    # World map
    wd = payload["world"]
    world = WorldMap(wd["width"], wd["height"])
    _decode_tiles(world, wd["tiles"])

    # Moriarty
    moriarty = _de_moriarty(payload["moriarty"])

    # WorldState
    ws = WorldState(world=world, moriarty=moriarty)
    ws.tick = payload.get("tick", 0)

    # World objects
    for od in payload.get("world_objects", []):
        try:
            ws.world_objects.append(_de_world_object(od))
        except Exception as e:
            print(f"[WARN] Could not load world object {od.get('type')}: {e}")

    # Entities
    from ..entities.animals import Animal
    for ed in payload.get("entities", []):
        kind = ed.get("kind")
        try:
            if kind == "animal":
                a = _de_animal(ed)
                if a:
                    ws.entities.append(a)
            elif kind == "item":
                item = _de_item(ed, (moriarty.x, moriarty.y))
                if item:
                    ws.entities.append(item)
        except Exception as e:
            print(f"[WARN] Could not load entity {ed}: {e}")

    # Conversation log
    ws.conversation_log = payload.get("conversation_log", [])

    print(f"[LOAD] World loaded from {path}  (tick {ws.tick})")
    return ws


def save_info(path: Path | str) -> dict | None:
    """Return metadata from a save file without fully loading it, or None."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        return {
            "tick":     payload.get("tick", 0),
            "saved_at": payload.get("saved_at", "unknown"),
            "version":  payload.get("version", 1),
        }
    except Exception:
        return None
