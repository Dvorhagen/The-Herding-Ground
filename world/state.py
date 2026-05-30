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
from ..entities.base import Entity, NemoEntity

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


def _ray_opacity(world, x0: int, y0: int, x1: int, y1: int) -> float:
    """
    Walk a ray from (x0,y0) to (x1,y1), accumulating the opacity of each
    unique intermediate tile (endpoints excluded). Returns total opacity;
    >= 1.0 means the target is fully occluded.
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
                if opacity >= 1.0:
                    return opacity
    return opacity


def _compute_visible(world, cx: int, cy: int) -> set:
    """
    Return the set of (x, y) positions visible from (cx, cy) within
    VISION_DISTANT, accounting for tile opacity.
    """
    visible = {(cx, cy)}
    for dy in range(-VISION_DISTANT, VISION_DISTANT + 1):
        for dx in range(-VISION_DISTANT, VISION_DISTANT + 1):
            if dx == 0 and dy == 0:
                continue
            if _dist(dx, dy) > VISION_DISTANT:
                continue
            if _ray_opacity(world, cx, cy, cx + dx, cy + dy) < 1.0:
                visible.add((cx + dx, cy + dy))
    return visible


@dataclass
class WorldState:
    world: WorldMap
    nemo: NemoEntity
    entities: list = field(default_factory=list)
    tick: int = 0
    injected_environment: str = ""   # PI inject — consumed next tick
    pending_memory_result: str = ""  # wiki retrieval result — consumed next tick

    def add_entity(self, entity: Entity):
        self.entities.append(entity)

    def remove_entity(self, entity: Entity):
        if entity in self.entities:
            self.entities.remove(entity)

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
        self.nemo.status.tick()

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
        nemo = self.nemo
        cx, cy = nemo.x, nemo.y

        # Precompute visible set once — shared by all three tiers
        visible = _compute_visible(self.world, cx, cy)

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
        nemo = self.nemo

        vision = self._build_vision_block()

        # Items on current tile
        items_here = self.get_items_at(nemo.x, nemo.y)
        items_str = (", ".join(i.name for i in items_here)
                     if items_here else "none")

        # Visible entities (within close range)
        visible_entities = self.get_entities_near(nemo.x, nemo.y,
                                                   radius=VISION_CLOSE)
        entity_lines = []
        for e in visible_entities:
            if e.x == nemo.x and e.y == nemo.y:
                continue
            dx, dy = e.x - nemo.x, e.y - nemo.y
            d = int(_dist(dx, dy))
            direction = _direction_name(dx, dy)
            entity_lines.append(
                f"  {e.name} ({d}m {direction})"
                + (" — right here, can pick up" if d == 0 else
                   " — move there to pick up"
                   if hasattr(e, 'item_type') else "")
            )

        entity_str = "\n".join(entity_lines) if entity_lines else "  none visible"
        recent = "\n  ".join(nemo.event_log[-5:]) if nemo.event_log else "none"

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

        return f"""[PERCEPTION — Tick {self.tick}]

{vision}

HERE (pick up immediately): {items_str}
Carrying: {nemo.describe_inventory()}
Status: {nemo.status.describe()}

Visible entities:
{entity_str}
{inject_block}{memory_block}
Recent events:
  {recent}"""
