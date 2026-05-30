"""
entities/animals.py
Animal entities with basic survival AI.
Each species has preferred terrain, a flee radius, and a wander tendency.

Tick loop (called by WorldState.advance_tick):
  1. If Moriarty is within flee_radius: flee directly away from him
  2. Else if random roll < wander_chance: wander to a random adjacent preferred tile
  3. Else: stay still

On death (health <= 0): entity is removed from world, raw meat is dropped.
"""

import random
from dataclasses import dataclass, field
from .base import Entity, EntityType, DIRECTIONS
from ..world.tiles import TileType


def _dist(dx: int, dy: int) -> float:
    return (dx * dx + dy * dy) ** 0.5


@dataclass
class Animal(Entity):
    species: str = "animal"
    health: int = 10
    max_health: int = 10
    flee_radius: int = 6
    wander_chance: float = 0.3
    preferred_tiles: tuple = field(default_factory=lambda: (TileType.GRASS,))
    alive: bool = True

    def __post_init__(self):
        self.entity_type = EntityType.CREATURE
        self.blocks = False

    def tick(self, world_state):
        if not self.alive:
            return
        moriarty = world_state.moriarty
        dx = self.x - moriarty.x
        dy = self.y - moriarty.y
        dist = _dist(dx, dy)

        if dist < self.flee_radius and not moriarty.hidden:
            self._flee(dx, dy, world_state.world)
        elif random.random() < self.wander_chance:
            self._wander(world_state.world)

    def _flee(self, dx: int, dy: int, world):
        """Move one step directly away from the threat."""
        step_x = (1 if dx > 0 else -1) if abs(dx) >= abs(dy) else 0
        step_y = (1 if dy > 0 else -1) if abs(dy) > abs(dx) else 0
        if step_x == 0 and step_y == 0:
            step_x = 1
        # Try primary direction, then perpendiculars
        for sx, sy in ((step_x, step_y), (step_y, step_x), (-step_y, -step_x)):
            if self.move(sx, sy, world):
                return

    def _wander(self, world):
        """Move one step in a random direction, preferring preferred tiles."""
        options = list(DIRECTIONS.values())
        random.shuffle(options)
        for dx, dy in options:
            nx, ny = self.x + dx, self.y + dy
            tile = world.get(nx, ny)
            if tile and tile.tile_type in self.preferred_tiles and world.is_passable(nx, ny):
                self.move(dx, dy, world)
                return
        # Fall back to any passable tile
        for dx, dy in options:
            if self.move(dx, dy, world):
                return

    def take_damage(self, amount: int, world_state) -> str:
        self.health -= amount
        if self.health <= 0:
            self.alive = False
            world_state.remove_entity(self)
            from .items import make_meat, make_feather
            meat = make_meat(self.x, self.y)
            world_state.add_entity(meat)
            # Birds drop a feather instead of meat
            if self.species == "bird":
                feather = make_feather(self.x, self.y)
                world_state.add_entity(feather)
                world_state.remove_entity(meat)
            return f"dead"
        return f"injured ({self.health}/{self.max_health} hp)"

    def describe(self) -> str:
        state = "injured" if self.health < self.max_health else ""
        return f"{self.name} ({self.species}){' — ' + state if state else ''}"


# ── Species ───────────────────────────────────────────────────────────────────

def make_rabbit(x: int, y: int) -> Animal:
    return Animal(
        name="rabbit", species="rabbit", x=x, y=y,
        symbol="r", color=(160, 140, 100),
        health=4, max_health=4,
        flee_radius=7,
        wander_chance=0.25,
        preferred_tiles=(TileType.GRASS, TileType.WETLAND),
    )

def make_deer(x: int, y: int) -> Animal:
    return Animal(
        name="deer", species="deer", x=x, y=y,
        symbol="d", color=(160, 120, 60),
        health=15, max_health=15,
        flee_radius=10,
        wander_chance=0.15,
        preferred_tiles=(TileType.FOREST, TileType.GRASS),
    )

def make_fox(x: int, y: int) -> Animal:
    return Animal(
        name="fox", species="fox", x=x, y=y,
        symbol="f", color=(200, 100, 40),
        health=8, max_health=8,
        flee_radius=4,
        wander_chance=0.35,
        preferred_tiles=(TileType.GRASS, TileType.FOREST, TileType.ROCKY),
    )

def make_bird(x: int, y: int) -> Animal:
    return Animal(
        name="bird", species="bird", x=x, y=y,
        symbol="b", color=(140, 170, 200),
        health=2, max_health=2,
        flee_radius=8,
        wander_chance=0.45,
        preferred_tiles=(TileType.GRASS, TileType.SAND, TileType.WETLAND),
    )
