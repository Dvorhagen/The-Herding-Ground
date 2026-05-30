"""
world/tiles.py
Tile definitions and the world map engine.
All tile types are designed for extensibility -- add new TileType entries
and update TILE_PROPERTIES to introduce new terrain.
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional


class TileType(Enum):
    GRASS      = auto()
    FOREST     = auto()
    WATER      = auto()
    MOUNTAIN   = auto()
    SAND       = auto()
    CAVE_FLOOR = auto()
    CAVE_WALL  = auto()
    PATH       = auto()


@dataclass
class TileProperties:
    name: str
    passable: bool
    symbol: str          # ASCII fallback / text description
    color: tuple         # RGB for pygame rendering (phosphor green palette)
    description: str     # What Nemo perceives


# Phosphor green palette -- all colors are shades of green on near-black
# to match the CRT aesthetic
PHOSPHOR_BG    = (10, 18, 10)
PHOSPHOR_DIM   = (20, 45, 20)
PHOSPHOR_MID   = (30, 90, 30)
PHOSPHOR_BRIGHT= (57, 181, 74)
PHOSPHOR_GLOW  = (100, 220, 100)
PHOSPHOR_WHITE = (160, 255, 160)

TILE_PROPERTIES: dict[TileType, TileProperties] = {
    TileType.GRASS:      TileProperties("Grass",       True,  ".",  PHOSPHOR_MID,   "open grassland"),
    TileType.FOREST:     TileProperties("Forest",      True,  "T",  PHOSPHOR_DIM,   "dense forest"),
    TileType.WATER:      TileProperties("Water",       False, "~",  (20, 60, 80),   "open water"),
    TileType.MOUNTAIN:   TileProperties("Mountain",    False, "^",  (60, 60, 60),   "sheer rock face"),
    TileType.SAND:       TileProperties("Sand",        True,  ":",  (100, 90, 40),  "sandy ground"),
    TileType.CAVE_FLOOR: TileProperties("Cave Floor",  True,  " ",  PHOSPHOR_DIM,   "dark cave floor"),
    TileType.CAVE_WALL:  TileProperties("Cave Wall",   False, "#",  (40, 40, 40),   "solid stone wall"),
    TileType.PATH:       TileProperties("Path",        True,  "+",  PHOSPHOR_BRIGHT,"worn dirt path"),
}


@dataclass
class Tile:
    tile_type: TileType
    # Future: items resting on tile, environmental effects, etc.
    items: list = field(default_factory=list)

    @property
    def props(self) -> TileProperties:
        return TILE_PROPERTIES[self.tile_type]

    @property
    def passable(self) -> bool:
        return self.props.passable and len([i for i in self.items if getattr(i, 'blocks', False)]) == 0


class WorldMap:
    """
    Holds the 2D grid of Tiles.
    Coordinate system: (col, row) aka (x, y), origin top-left.
    """

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        # Default fill: grass
        self._grid: list[list[Tile]] = [
            [Tile(TileType.GRASS) for _ in range(width)]
            for _ in range(height)
        ]

    def get(self, x: int, y: int) -> Optional[Tile]:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self._grid[y][x]
        return None

    def set(self, x: int, y: int, tile_type: TileType):
        if 0 <= x < self.width and 0 <= y < self.height:
            self._grid[y][x] = Tile(tile_type)

    def is_passable(self, x: int, y: int) -> bool:
        tile = self.get(x, y)
        return tile is not None and tile.passable

    def get_perception_grid(self, cx: int, cy: int, radius: int = 3) -> str:
        """
        Returns a text description of the tiles visible from (cx, cy)
        within the given radius. This is what gets fed to Nemo's context.
        Cardinal directions are labeled.
        """
        lines = []
        for dy in range(-radius, radius + 1):
            row = []
            for dx in range(-radius, radius + 1):
                x, y = cx + dx, cy + dy
                if dx == 0 and dy == 0:
                    row.append("@")  # Nemo's position
                else:
                    tile = self.get(x, y)
                    if tile is None:
                        row.append("?")  # out of bounds
                    else:
                        row.append(tile.props.symbol)
            lines.append(" ".join(row))
        return "\n".join(lines)

    def describe_surroundings(self, cx: int, cy: int) -> str:
        """
        Returns a structured text perception block for Nemo's prompt.
        """
        directions = {
            "North": (0, -1),
            "South": (0, 1),
            "East":  (1, 0),
            "West":  (-1, 0),
            "NE":    (1, -1),
            "NW":    (-1, -1),
            "SE":    (1, 1),
            "SW":    (-1, 1),
        }
        desc = []
        current = self.get(cx, cy)
        desc.append(f"Underfoot: {current.props.description if current else 'unknown'}")
        for dir_name, (dx, dy) in directions.items():
            tile = self.get(cx + dx, cy + dy)
            if tile:
                desc.append(f"  {dir_name}: {tile.props.description}")
            else:
                desc.append(f"  {dir_name}: nothing — the world ends here")
        return "\n".join(desc)
