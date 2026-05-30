"""
world/state.py
WorldState: the central game state. Holds the map, all entities,
and provides query methods used by actions and the brain.

Vision is distance-graded at 1m scale:
  Immediate (0m):   your tile
  Close    (1-3m):  adjacent tiles, full detail
  Nearby   (4-8m):  visible features, moderate detail
  Distant  (9-15m): shapes and impressions only
"""

from dataclasses import dataclass, field
from typing import Optional
from .tiles import WorldMap, TileType
from ..entities.base import Entity, MoriartyEntity

# Vision radii (in tiles = meters at 1m scale)
VISION_CLOSE   = 3
VISION_NEARBY  = 8
VISION_DISTANT = 15


def _direction_name(dx: int, dy: int) -> str:
    """Convert a dx,dy offset to a compass direction string."""
    if dx == 0 and dy == 0:
        return "here"
    parts = []
    if dy < 0: parts.append("north")
    if dy > 0: parts.append("south")
    if dx > 0: parts.append("east")
    if dx < 0: parts.append("west")
    return "-".join(parts)


def _dist(dx: int, dy: int) -> float:
    return (dx*dx + dy*dy) ** 0.5


def _ray_opacity(world, x0: int, y0: int, x1: int, y1: int, object_opacity: dict = None) -> float:
    """
    Walk a ray from (x0,y0) to (x1,y1), accumulating the opacity of each
    unique intermediate tile (endpoints excluded). Returns total opacity;
    >= 1.0 means the target is fully occluded.
    object_opacity: optional dict mapping (x, y) -> extra opacity from world objects.
    """
    dx = x1 - x0
    dy = y1 - y0
    steps = max(abs(dx), abs(dy)) * 4  # quarter-tile precision
    if steps == 0:
        return 0.0

    visited = set()
    opacity = 0.0
    for i in range(1, steps):
        t = i / steps
        x = int(x0 + dx * t + 0.5)
        y = int(y0 + dy * t + 0.5)
        if (x, y) == (x1, y1):
            break
        if (x, y) != (x0, y0) and (x, y) not in visited:
            visited.add((x, y))
            tile = world.get(x, y)
            if tile:
                opacity += tile.props.opacity
            if object_opacity:
                opacity += object_opacity.get((x, y), 0.0)
            if opacity >= 1.0:
                return opacity
    return opacity


def _build_object_opacity(world_objects) -> dict:
    """Build a (x, y) -> total_opacity map from world objects."""
    result = {}
    for obj in world_objects:
        if obj.opacity > 0.0:
            result[(obj.x, obj.y)] = result.get((obj.x, obj.y), 0.0) + obj.opacity
    return result


def _compute_visible(world, cx: int, cy: int, object_opacity: dict = None) -> set:
    """
    Return the set of (x, y) positions visible from (cx, cy) within
    VISION_DISTANT, accounting for tile and world object opacity.
    """
    visible = {(cx, cy)}
    for dy in range(-VISION_DISTANT, VISION_DISTANT + 1):
        for dx in range(-VISION_DISTANT, VISION_DISTANT + 1):
            if dx == 0 and dy == 0:
                continue
            if _dist(dx, dy) > VISION_DISTANT:
                continue
            if _ray_opacity(world, cx, cy, cx + dx, cy + dy, object_opacity) < 1.0:
                visible.add((cx + dx, cy + dy))
    return visible


@dataclass
class WorldState:
    world: WorldMap
    moriarty: MoriartyEntity
    entities: list = field(default_factory=list)
    world_objects: list = field(default_factory=list)
    tick: int = 0
    injected_environment: str = ""   # PI inject — consumed next tick
    pending_memory_result: str = ""  # wiki retrieval result — consumed next tick
    pending_messages: list = field(default_factory=list)  # [{from_name, to_id, message, tick}]
    visible_tiles: set = field(default_factory=set)

    def add_entity(self, entity: Entity):
        self.entities.append(entity)

    def remove_entity(self, entity: Entity):
        if entity in self.entities:
            self.entities.remove(entity)

    def add_object(self, obj):
        self.world_objects.append(obj)

    def remove_object(self, obj):
        if obj in self.world_objects:
            self.world_objects.remove(obj)

    def get_objects_at(self, x: int, y: int) -> list:
        return [o for o in self.world_objects if o.x == x and o.y == y]

    def get_objects_near(self, x: int, y: int, radius: int = 5) -> list:
        return [o for o in self.world_objects if _dist(o.x - x, o.y - y) <= radius]

    def get_items_at(self, x: int, y: int) -> list:
        from ..entities.items import Item
        return [e for e in self.entities
                if isinstance(e, Item) and e.x == x and e.y == y]

    def get_entities_at(self, x: int, y: int) -> list:
        return [e for e in self.entities if e.x == x and e.y == y]

    def get_entities_near(self, x: int, y: int, radius: int = 15) -> list:
        return [
            e for e in self.entities
            if _dist(e.x - x, e.y - y) <= radius
        ]

    def advance_tick(self):
        self.tick += 1
        self.moriarty.status.tick()
        # Determine environmental healing bonuses
        near_fire = any(
            getattr(o, 'lit', False)
            for o in self.get_objects_near(self.moriarty.x, self.moriarty.y, radius=3)
            if hasattr(o, 'lit')
        )
        # Tick combat state (bleeding, infection, healing, shock, grapple)
        self.moriarty.combat_state.tick(
            resting=self.moriarty.is_resting,
            warm=near_fire,
        )
        if self.moriarty.combat_state.pending_grapple_msg:
            self.moriarty.log_event(self.moriarty.combat_state.pending_grapple_msg)
            self.moriarty.combat_state.pending_grapple_msg = ""
        from ..entities.animals import Animal
        for entity in list(self.entities):
            if isinstance(entity, Animal) and entity.alive:
                entity.tick(self)

    def _describe_tile_at(self, x: int, y: int) -> str:
        tile = self.world.get(x, y)
        if tile is None:
            return "edge of the world"
        return tile.props.description

    def _build_vision_block(self) -> str:
        """
        Build distance-graded vision description.
        At 1m scale, 15 tiles = 15 meters — a natural human sight line in open terrain.
        """
        moriarty = self.moriarty
        cx, cy = moriarty.x, moriarty.y

        # Precompute visible set once — shared by all three tiers, exposed for renderers
        obj_opacity = _build_object_opacity(self.world_objects)
        visible = _compute_visible(self.world, cx, cy, obj_opacity)
        self.visible_tiles = visible

        # --- Immediate: current position ---
        current = self._describe_tile_at(cx, cy)

        # --- Close (1-3m): group by direction, show dominant terrain ---
        close_by = {}
        for dy in range(-VISION_CLOSE, VISION_CLOSE + 1):
            for dx in range(-VISION_CLOSE, VISION_CLOSE + 1):
                if dx == 0 and dy == 0:
                    continue
                d = _dist(dx, dy)
                if d > VISION_CLOSE:
                    continue
                if (cx + dx, cy + dy) not in visible:
                    continue
                tile = self.world.get(cx + dx, cy + dy)
                if tile is None:
                    continue
                direction = _direction_name(dx, dy)
                if direction not in close_by:
                    close_by[direction] = (d, tile.props.description)
                elif d < close_by[direction][0]:
                    close_by[direction] = (d, tile.props.description)

        close_lines = [f"  {dir}: {desc}"
                       for dir, (_, desc) in sorted(close_by.items())]

        # --- Nearby (4-8m): group by terrain type ---
        nearby_types = {}
        for dy in range(-VISION_NEARBY, VISION_NEARBY + 1):
            for dx in range(-VISION_NEARBY, VISION_NEARBY + 1):
                d = _dist(dx, dy)
                if d <= VISION_CLOSE or d > VISION_NEARBY:
                    continue
                if (cx + dx, cy + dy) not in visible:
                    continue
                tile = self.world.get(cx + dx, cy + dy)
                if tile is None:
                    continue
                tname = tile.props.name
                direction = _direction_name(dx, dy)
                if tname not in nearby_types:
                    nearby_types[tname] = set()
                nearby_types[tname].add(direction)

        nearby_lines = []
        for tname, dirs in sorted(nearby_types.items()):
            dir_str = ", ".join(sorted(dirs)[:3])
            nearby_lines.append(f"  {tname} to the {dir_str}")

        # --- Distant (9-15m): impressions only ---
        distant_types = {}
        for dy in range(-VISION_DISTANT, VISION_DISTANT + 1):
            for dx in range(-VISION_DISTANT, VISION_DISTANT + 1):
                d = _dist(dx, dy)
                if d <= VISION_NEARBY or d > VISION_DISTANT:
                    continue
                if (cx + dx, cy + dy) not in visible:
                    continue
                tile = self.world.get(cx + dx, cy + dy)
                if tile is None:
                    continue
                tname = tile.props.name
                direction = _direction_name(dx, dy)
                if tname not in distant_types:
                    distant_types[tname] = set()
                distant_types[tname].add(direction)

        distant_lines = []
        for tname, dirs in sorted(distant_types.items()):
            dir_str = ", ".join(sorted(dirs)[:2])
            distant_lines.append(f"  {tname} in the distance ({dir_str})")

        # Assemble
        lines = [f"Underfoot: {current}"]
        if close_lines:
            lines.append("Close by:")
            lines.extend(close_lines[:12])  # cap for token budget
        if nearby_lines:
            lines.append("Visible nearby:")
            lines.extend(nearby_lines[:8])
        if distant_lines:
            lines.append("Distant:")
            lines.extend(distant_lines[:6])

        return "\n".join(lines)

    def build_perception_block(self) -> str:
        moriarty = self.moriarty

        vision = self._build_vision_block()

        # Items on current tile
        items_here = self.get_items_at(moriarty.x, moriarty.y)
        items_str = (", ".join(i.name for i in items_here)
                     if items_here else "none")

        from ..entities.animals import Animal

        # Visible entities (within close range)
        visible_entities = self.get_entities_near(moriarty.x, moriarty.y,
                                                   radius=VISION_CLOSE)
        entity_lines = []
        for e in visible_entities:
            if e.x == moriarty.x and e.y == moriarty.y:
                continue
            dx, dy = e.x - moriarty.x, e.y - moriarty.y
            d = int(_dist(dx, dy))
            direction = _direction_name(dx, dy)
            if isinstance(e, Animal):
                hp_str = f" [{e.health}/{e.max_health}hp]" if e.health < e.max_health else ""
                entity_lines.append(f"  {e.name} ({d}m {direction}){hp_str} — attack, or approach cautiously")
            elif hasattr(e, 'item_type'):
                hint = " — right here, pick up" if d == 0 else " — move closer to pick up"
                entity_lines.append(f"  {e.name} ({d}m {direction}){hint}")
            else:
                entity_lines.append(f"  {e.name} ({d}m {direction})")

        entity_str = "\n".join(entity_lines) if entity_lines else "  none visible"

        # World objects within interaction range
        nearby_objects = self.get_objects_near(moriarty.x, moriarty.y, radius=VISION_CLOSE)
        object_lines = []
        for o in nearby_objects:
            dx, dy = o.x - moriarty.x, o.y - moriarty.y
            d = int(_dist(dx, dy))
            direction = _direction_name(dx, dy)
            verbs = list(o.interactions().keys())
            verb_str = f" — {', '.join(verbs)}" if verbs else ""
            object_lines.append(f"  {o.name} ({d}m {direction}){verb_str}")
        object_str = "\n".join(object_lines) if object_lines else "  none nearby"

        recent = "\n  ".join(moriarty.event_log[-5:]) if moriarty.event_log else "none"

        # Memory index — brief summary of what's stored so Mo knows what to read
        from ..memory import wiki as _wiki
        mem_pages = _wiki.list_pages()
        mem_by_cat = {}
        for p in mem_pages:
            cat = p.split("/")[0]
            mem_by_cat[cat] = mem_by_cat.get(cat, 0) + 1
        mem_index = "  " + "  ".join(
            f"{cat}: {n} page{'s' if n != 1 else ''}"
            for cat, n in sorted(mem_by_cat.items())
        ) if mem_by_cat else "  (empty)"

        # Incoming messages addressed to Moriarty or broadcast
        msg_lines = []
        remaining = []
        for m in self.pending_messages:
            if m["to_id"] in (moriarty.id, "broadcast"):
                msg_lines.append(f'  {m["from_name"]}: "{m["message"]}"')
            else:
                remaining.append(m)
        self.pending_messages = remaining
        message_block = f"\n[MESSAGES]\n" + "\n".join(msg_lines) + "\n" if msg_lines else ""

        # PI inject
        inject_block = ""
        if self.injected_environment:
            inject_block = f"\n[ENVIRONMENT]\n{self.injected_environment}\n"
            self.injected_environment = ""

        # Memory retrieval result from previous tick
        memory_block = ""
        if self.pending_memory_result:
            memory_block = f"\n[MEMORY RETRIEVED]\n{self.pending_memory_result}\n"
            self.pending_memory_result = ""

        hidden_str = "  (you are hidden)" if moriarty.hidden else ""
        equip_str = moriarty.describe_equipment()

        # Body status — only shown when wounded
        cs = moriarty.combat_state
        body_block = ""
        if cs.any_wounds or cs.blood_loss > 0 or cs.grappled_with:
            body_block = f"\n[BODY STATUS]\n{cs.describe_body()}\n{cs.describe_conditions()}\n"

        return f"""[PERCEPTION — Tick {self.tick}]

{vision}

HERE (pick up immediately): {items_str}
Carrying: {moriarty.describe_inventory()}
Equipped: {equip_str}
Status: {moriarty.status.describe()}{hidden_str}
{body_block}
Visible entities:
{entity_str}

World objects (interact by using the verb as your action):
{object_str}

Memory index:
{mem_index}
{message_block}{inject_block}{memory_block}
Recent events:
  {recent}"""
