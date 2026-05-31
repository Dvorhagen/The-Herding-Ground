"""
world/tiles.py
Tile definitions and the infinite chunk-based world map engine.

WorldMap generates terrain on demand using value noise — no fixed grid.
Chunks are 32×32 tiles, generated deterministically from (cx, cy, seed).
Only modified chunks need to be saved; clean chunks regenerate for free.

Terrain layers (all continuous, no chunk seams):
  elevation  → MOUNTAIN / ROCKY / GRASS / SAND
  moisture   → WATER (lakes) / WETLAND / SAND (beaches)
  forest     → FOREST within GRASS zones
  road       → PATH strips near world origin
  river      → precomputed waypoint path, rasterised per-chunk
"""

import random
import math
import threading
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional


# ── Tile types and properties ─────────────────────────────────────────────────

class TileType(Enum):
    GRASS      = auto()
    FOREST     = auto()
    WATER      = auto()
    MOUNTAIN   = auto()
    SAND       = auto()
    CAVE_FLOOR = auto()
    CAVE_WALL  = auto()
    PATH       = auto()
    WETLAND    = auto()
    ROCKY      = auto()


@dataclass
class TileProperties:
    name: str
    passable: bool
    symbol: str
    color: tuple
    description: str
    opacity: float = 0.0


PHOSPHOR_BG    = (10, 18, 10)
PHOSPHOR_DIM   = (20, 45, 20)
PHOSPHOR_MID   = (30, 90, 30)
PHOSPHOR_BRIGHT= (57, 181, 74)
PHOSPHOR_GLOW  = (100, 220, 100)
PHOSPHOR_WHITE = (160, 255, 160)

TILE_PROPERTIES: dict[TileType, TileProperties] = {
    TileType.GRASS:      TileProperties("Grass",      True,  ".",  PHOSPHOR_MID,    "open grassland",           opacity=0.0),
    TileType.FOREST:     TileProperties("Forest",     True,  "T",  PHOSPHOR_DIM,    "dense forest",             opacity=0.5),
    TileType.WATER:      TileProperties("Water",      False, "~",  (20, 60, 80),    "open water",               opacity=0.0),
    TileType.MOUNTAIN:   TileProperties("Mountain",   False, "^",  (60, 60, 60),    "sheer rock face",          opacity=1.0),
    TileType.SAND:       TileProperties("Sand",       True,  ":",  (100, 90, 40),   "sandy ground",             opacity=0.0),
    TileType.CAVE_FLOOR: TileProperties("Cave Floor", True,  " ",  PHOSPHOR_DIM,    "dark cave floor",          opacity=0.0),
    TileType.CAVE_WALL:  TileProperties("Cave Wall",  False, "#",  (40, 40, 40),    "solid stone wall",         opacity=1.0),
    TileType.PATH:       TileProperties("Path",       True,  "+",  PHOSPHOR_BRIGHT, "worn dirt path",           opacity=0.0),
    TileType.WETLAND:    TileProperties("Wetland",    True,  ";",  (20, 55, 35),    "waterlogged boggy ground", opacity=0.1),
    TileType.ROCKY:      TileProperties("Rocky",      True,  ",",  (65, 75, 55),    "loose rocky ground",       opacity=0.0),
}


@dataclass
class Tile:
    tile_type: TileType
    items: list = field(default_factory=list)

    @property
    def props(self) -> TileProperties:
        return TILE_PROPERTIES[self.tile_type]

    @property
    def passable(self) -> bool:
        return self.props.passable and not any(
            getattr(i, 'blocks', False) for i in self.items
        )


# ── Value noise (no external dependencies) ────────────────────────────────────

def _hash(x: int, y: int, seed: int) -> float:
    """Deterministic pseudo-random float [0, 1] for integer grid point."""
    h = (seed & 0xFFFFFFFF) ^ (x * 374761393) ^ (y * 668265263)
    h = ((h >> 13) ^ h) * 1274126177
    h = (h >> 16) ^ h
    return (h & 0x7FFFFFFF) / 0x7FFFFFFF


def _smooth(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)   # smoothstep


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * _smooth(t)


def _vnoise(x: float, y: float, seed: int) -> float:
    """Bilinear value noise, smoothstep interpolated."""
    xi, yi = int(math.floor(x)), int(math.floor(y))
    xf, yf = x - xi, y - yi
    v00 = _hash(xi,     yi,     seed)
    v10 = _hash(xi + 1, yi,     seed)
    v01 = _hash(xi,     yi + 1, seed)
    v11 = _hash(xi + 1, yi + 1, seed)
    return _lerp(_lerp(v00, v10, xf), _lerp(v01, v11, xf), yf)


def _fbm(x: float, y: float, seed: int, octaves: int = 4) -> float:
    """Fractal Brownian Motion: stacked octaves of value noise → [0, ~1]."""
    val, amp, freq = 0.0, 0.5, 1.0
    for i in range(octaves):
        val  += amp * _vnoise(x * freq, y * freq, seed + i * 997)
        amp  *= 0.5
        freq *= 2.0
    return val    # approximately 0–1 (can slightly exceed 1 at low octave count)


# ── River precomputation ──────────────────────────────────────────────────────

_RIVER_STEP = 0.6     # tiles per step (sub-tile precision)
_RIVER_STEPS = 3000   # max length


def _generate_river(seed: int) -> list[tuple[float, float]]:
    """
    Precompute a river as world-space (float x, y) waypoints.
    Starts north of origin, flows generally south with meandering.
    Stored in WorldMap and checked during chunk generation.
    """
    rng = random.Random(seed ^ 0xDEADBEEF)
    x = rng.uniform(-40, 40)
    y = float(rng.randint(-600, -200))
    path: list[tuple[float, float]] = [(x, y)]
    for _ in range(_RIVER_STEPS):
        angle = math.pi * 0.5 + rng.gauss(0, 0.25)   # mostly southward
        x += math.cos(angle) * _RIVER_STEP
        y += math.sin(angle) * _RIVER_STEP
        path.append((x, y))
        if y > 1500:
            break
    return path


def _precompute_river_map(river: list) -> dict:
    """
    Precompute {(wx, wy): TileType} for all tiles within the river corridor.
    Done once at WorldMap init — O(waypoints × area) but cheap in practice.
    Chunk generation then just does a dict lookup instead of iterating waypoints.
    """
    river_map: dict[tuple[int, int], "TileType"] = {}
    _WATER_DSQ   = 9    # dist < 3 tiles → water
    _SAND_DSQ    = 20   # dist < ~4.5 tiles → sand
    _WETLAND_DSQ = 36   # dist < 6 tiles → wetland

    _priority = {TileType.WATER: 0, TileType.SAND: 1, TileType.WETLAND: 2}

    for rx, ry in river:
        irx, iry = int(round(rx)), int(round(ry))
        for dy in range(-7, 8):
            for dx in range(-7, 8):
                dsq = (rx - (irx + dx)) ** 2 + (ry - (iry + dy)) ** 2
                if dsq < _WATER_DSQ:    tt = TileType.WATER
                elif dsq < _SAND_DSQ:   tt = TileType.SAND
                elif dsq < _WETLAND_DSQ:tt = TileType.WETLAND
                else:                   continue
                key = (irx + dx, iry + dy)
                existing = river_map.get(key)
                if existing is None or _priority[tt] < _priority[existing]:
                    river_map[key] = tt
    return river_map


# ── Road centre-line (meanders slightly, passes through origin) ───────────────

def _road_y_at(x: int, seed: int) -> float:
    """Y-coordinate of the main E-W road at world-x. Meanders gently."""
    return _vnoise(x / 300.0, 0.5, seed ^ 0xCAFE) * 12 - 6


def _road_x_at(y: int, seed: int) -> float:
    """X-coordinate of the main N-S road at world-y."""
    return _vnoise(0.5, y / 300.0, seed ^ 0xBEEF) * 12 - 6


# ── Chunk-level terrain classifier ───────────────────────────────────────────

_NOISE_SCALE = 1.0 / 90.0    # ~90m per noise feature cell


def _tile_type_at(wx: int, wy: int, seed: int,
                  river_map: dict) -> TileType:
    """
    Classify world tile (wx, wy) from continuous noise + precomputed river map + road.
    river_map: {(wx,wy): TileType} precomputed at WorldMap init — O(1) lookup.
    """
    # ── River (O(1) lookup) ───────────────────────────────────────────────────
    river_tile = river_map.get((wx, wy))
    if river_tile is not None:
        return river_tile

    nx = wx * _NOISE_SCALE
    ny = wy * _NOISE_SCALE

    elev   = _fbm(nx,       ny,       seed,        octaves=4)
    moist  = _fbm(nx + 200, ny + 200, seed + 1000, octaves=3)
    forest = _fbm(nx + 400, ny + 400, seed + 2000, octaves=2)

    # ── Terrain ───────────────────────────────────────────────────────────────
    if elev > 0.80:    return TileType.MOUNTAIN
    if elev > 0.70:    return TileType.ROCKY
    if moist > 0.75 and elev < 0.45:
                       return TileType.WATER
    if moist > 0.62 and elev < 0.52:
                       return TileType.WETLAND
    if forest > 0.58 and elev < 0.70:
                       return TileType.FOREST
    if moist > 0.50 and elev < 0.38:
                       return TileType.SAND
    if elev > 0.60 and forest < 0.35:
                       return TileType.ROCKY

    # ── Roads ─────────────────────────────────────────────────────────────────
    if abs(wy - _road_y_at(wx, seed)) < 1.5 and elev < 0.68:
        return TileType.PATH
    if abs(wx - _road_x_at(wy, seed)) < 1.5 and elev < 0.68:
        return TileType.PATH

    return TileType.GRASS


# ── Infinite chunk-based WorldMap ─────────────────────────────────────────────

CHUNK_SIZE   = 32
WORLD_EXTENT = 500_000     # ±500 km; effectively infinite at 1 m/tile


class WorldMap:
    """
    Infinite (±500 km) procedural world map using 32×32 tile chunks.

    Interface unchanged from the fixed-grid version:
      get(x, y)  →  Tile | None
      set(x, y, tile_type)
      is_passable(x, y)  →  bool

    width / height return WORLD_EXTENT*2 for backwards compatibility with
    any code that uses them as loose bounds (renderers, clamping, etc.).
    """

    def __init__(self, seed: int = 42):
        self.seed   = seed
        self.width  = WORLD_EXTENT * 2    # compatibility shim
        self.height = WORLD_EXTENT * 2    # compatibility shim
        self._chunks:          dict[tuple, list] = {}
        self._modified_chunks: set[tuple]        = set()
        self._chunk_lock = threading.Lock()
        # Precompute river tile map once — O(1) per-tile lookup during generation
        self._river_map: dict[tuple[int,int], TileType] = \
            _precompute_river_map(_generate_river(seed))

    # ── Chunk coordinate helpers ──────────────────────────────────────────────

    @staticmethod
    def _chunk_of(x: int, y: int) -> tuple[int, int]:
        # Python's floor-division handles negatives correctly
        return x // CHUNK_SIZE, y // CHUNK_SIZE

    @staticmethod
    def _local(x: int, y: int) -> tuple[int, int]:
        return x % CHUNK_SIZE, y % CHUNK_SIZE

    # ── Chunk generation and caching ─────────────────────────────────────────

    def _ensure_chunk(self, cx: int, cy: int):
        if (cx, cy) in self._chunks:
            return
        with self._chunk_lock:
            # Double-checked locking: another thread may have generated it
            if (cx, cy) not in self._chunks:
                self._chunks[(cx, cy)] = self._generate_chunk(cx, cy)

    def _generate_chunk(self, cx: int, cy: int) -> list:
        """Generate a fresh 32×32 tile array for chunk (cx, cy)."""
        river_map = self._river_map
        seed = self.seed
        grid = []
        for ly in range(CHUNK_SIZE):
            row = []
            wx_base = cx * CHUNK_SIZE
            wy = cy * CHUNK_SIZE + ly
            for lx in range(CHUNK_SIZE):
                tt = _tile_type_at(wx_base + lx, wy, seed, river_map)
                row.append(Tile(tt))
            grid.append(row)
        return grid

    # ── Public interface ──────────────────────────────────────────────────────

    def get(self, x: int, y: int) -> Optional[Tile]:
        if not (-WORLD_EXTENT <= x < WORLD_EXTENT and
                -WORLD_EXTENT <= y < WORLD_EXTENT):
            return None
        cx, cy = self._chunk_of(x, y)
        self._ensure_chunk(cx, cy)
        lx, ly = self._local(x, y)
        return self._chunks[(cx, cy)][ly][lx]

    def set(self, x: int, y: int, tile_type: TileType):
        if not (-WORLD_EXTENT <= x < WORLD_EXTENT and
                -WORLD_EXTENT <= y < WORLD_EXTENT):
            return
        cx, cy = self._chunk_of(x, y)
        self._ensure_chunk(cx, cy)
        lx, ly = self._local(x, y)
        self._chunks[(cx, cy)][ly][lx] = Tile(tile_type)
        self._modified_chunks.add((cx, cy))

    def is_passable(self, x: int, y: int) -> bool:
        tile = self.get(x, y)
        return tile is not None and tile.passable

    def get_loaded_chunk_keys(self) -> set:
        return set(self._chunks.keys())

    # ── Perception helpers (unchanged interface) ──────────────────────────────

    def describe_surroundings(self, cx: int, cy: int) -> str:
        directions = {
            "North": (0, -1), "South": (0, 1),
            "East":  (1, 0),  "West":  (-1, 0),
            "NE":    (1, -1), "NW":    (-1, -1),
            "SE":    (1, 1),  "SW":    (-1, 1),
        }
        current = self.get(cx, cy)
        desc = [f"Underfoot: {current.props.description if current else 'unknown'}"]
        for dir_name, (dx, dy) in directions.items():
            tile = self.get(cx + dx, cy + dy)
            desc.append(f"  {dir_name}: {tile.props.description if tile else 'the world ends here'}")
        return "\n".join(desc)
