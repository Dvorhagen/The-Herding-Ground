"""
world/state.py
WorldState: the central game state. Holds the map, all entities,
and provides query methods used by actions and the brain.
"""

from dataclasses import dataclass, field
from typing import Optional
from .tiles import WorldMap
from ..entities.base import Entity, NemoEntity


@dataclass
class WorldState:
    world: WorldMap
    nemo: NemoEntity
    entities: list = field(default_factory=list)    # All non-Nemo entities
    tick: int = 0

    def add_entity(self, entity: Entity):
        self.entities.append(entity)

    def remove_entity(self, entity: Entity):
        if entity in self.entities:
            self.entities.remove(entity)

    def get_items_at(self, x: int, y: int) -> list:
        from ..entities.items import Item
        return [e for e in self.entities if isinstance(e, Item) and e.x == x and e.y == y]

    def get_entities_at(self, x: int, y: int) -> list:
        return [e for e in self.entities if e.x == x and e.y == y]

    def get_entities_near(self, x: int, y: int, radius: int = 3) -> list:
        return [
            e for e in self.entities
            if abs(e.x - x) <= radius and abs(e.y - y) <= radius
        ]

    def advance_tick(self):
        """Advance the world by one tick. Update status effects etc."""
        self.tick += 1
        self.nemo.status.tick()

    def build_perception_block(self) -> str:
        """
        Builds the full [PERCEPTION] block fed to Nemo each tick.
        """
        nemo = self.nemo
        surroundings = self.world.describe_surroundings(nemo.x, nemo.y)

        # Items strictly on Nemo's tile
        items_here = self.get_items_at(nemo.x, nemo.y)
        items_str = ", ".join(i.name for i in items_here) if items_here else "none"

        # Nearby items with directions (excluding items on current tile)
        nearby_entities = self.get_entities_near(nemo.x, nemo.y, radius=5)
        nearby_lines = []
        for e in nearby_entities:
            if e.x == nemo.x and e.y == nemo.y:
                continue  # already shown in items_here
            dx = e.x - nemo.x
            dy = e.y - nemo.y
            dist = max(abs(dx), abs(dy))
            dir_x = ("E" if dx > 0 else "W") if dx != 0 else ""
            dir_y = ("S" if dy > 0 else "N") if dy != 0 else ""
            direction = dir_y + dir_x if (dir_y or dir_x) else "here"
            nearby_lines.append(f"{e.name} ({dist} tiles {direction}) — move to it first to pick up")

        nearby_str = "\n  ".join(nearby_lines) if nearby_lines else "none"
        recent = "\n  ".join(nemo.event_log[-5:]) if nemo.event_log else "none"

        return f"""[PERCEPTION — Tick {self.tick}]
Position: ({nemo.x}, {nemo.y})
{surroundings}

ON YOUR TILE (can pick up now): {items_str}
Carrying: {nemo.describe_inventory()}
Status: {nemo.status.describe()}

NEARBY (must move to these first):
  {nearby_str}

Recent events:
  {recent}"""
