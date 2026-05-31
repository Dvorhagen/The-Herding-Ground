"""
world/mapgen.py
World population helpers for the infinite chunk-based WorldMap.

generate_world() is gone — WorldMap(seed) generates itself on demand.
This module provides:
  find_spawn(world)                  — good starting position near origin
  populate_natural_objects(ws, seed) — scatter world objects near spawn
  populate_animals(ws, seed)         — scatter animals near spawn
"""

import random
import math
from .tiles import WorldMap, TileType


# ── Spawn finder ──────────────────────────────────────────────────────────────

def find_spawn(world: WorldMap) -> tuple[int, int]:
    """
    Find a good spawn point near (0, 0).
    Prefers PATH tiles (road crossing), then any passable tile.
    Searches in expanding rings from the origin.
    """
    # PATH intersection near origin
    for radius in range(0, 80):
        for angle_step in range(max(1, radius * 4)):
            angle = (2 * math.pi * angle_step) / max(1, radius * 4)
            x = int(round(radius * math.cos(angle)))
            y = int(round(radius * math.sin(angle)))
            tile = world.get(x, y)
            if not tile or tile.tile_type != TileType.PATH:
                continue
            neighbors = [world.get(x + dx, y + dy)
                         for dx, dy in ((1,0),(-1,0),(0,1),(0,-1))]
            if sum(1 for t in neighbors if t and t.tile_type == TileType.PATH) >= 2:
                return x, y

    # Any path tile
    for radius in range(0, 80):
        for angle_step in range(max(1, radius * 4)):
            angle = (2 * math.pi * angle_step) / max(1, radius * 4)
            x = int(round(radius * math.cos(angle)))
            y = int(round(radius * math.sin(angle)))
            tile = world.get(x, y)
            if tile and tile.tile_type == TileType.PATH:
                return x, y

    # Any passable tile
    for radius in range(0, 120):
        for angle_step in range(max(1, radius * 4)):
            angle = (2 * math.pi * angle_step) / max(1, radius * 4)
            x = int(round(radius * math.cos(angle)))
            y = int(round(radius * math.sin(angle)))
            if world.is_passable(x, y):
                return x, y

    return 0, 0


# ── Natural object population ─────────────────────────────────────────────────

def populate_natural_objects(world_state, seed: int = None,
                              cx: int = 0, cy: int = 0,
                              radius: int = 180):
    """
    Scatter natural world objects in a radius around (cx, cy).
    Called once after world creation and whenever a new area is explored
    (future: chunk-based sparse population).
    """
    from .objects import (make_boulder, make_bush, make_fallen_log,
                          make_wild_mushroom, make_flower_patch,
                          make_tree, make_hollow_tree, make_reed_bed,
                          make_herb_patch)

    rng = random.Random(seed)
    world = world_state.world

    # Pre-generate all chunks in scatter radius so lazy generation doesn't
    # fire thousands of times during the scatter loop (huge speed-up).
    from .tiles import CHUNK_SIZE
    for chunk_y in range((cy - radius) // CHUNK_SIZE, (cy + radius) // CHUNK_SIZE + 1):
        for chunk_x in range((cx - radius) // CHUNK_SIZE, (cx + radius) // CHUNK_SIZE + 1):
            world._ensure_chunk(chunk_x, chunk_y)

    def _scatter(make_fn, allowed, count, min_spacing=6, extra=None):
        placed = []
        attempts = 0
        while len(placed) < count and attempts < count * 150:
            x = cx + rng.randint(-radius, radius)
            y = cy + rng.randint(-radius, radius)
            tile = world.get(x, y)
            if not tile or tile.tile_type not in allowed:
                attempts += 1
                continue
            if any(abs(x-px) < min_spacing and abs(y-py) < min_spacing
                   for px, py in placed):
                attempts += 1
                continue
            if extra and not extra(x, y):
                attempts += 1
                continue
            world_state.add_object(make_fn(x, y))
            placed.append((x, y))
            attempts += 1

    forest  = {TileType.FOREST}
    open_   = {TileType.GRASS, TileType.WETLAND}
    rocky   = {TileType.ROCKY, TileType.MOUNTAIN}
    wet     = {TileType.WETLAND, TileType.SAND}

    def near_water(x, y):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                t = world.get(x + dx, y + dy)
                if t and t.tile_type == TileType.WATER:
                    return True
        return False

    _scatter(make_boulder,       rocky,                  40, min_spacing=8)
    _scatter(make_boulder,       {TileType.GRASS},       10, min_spacing=25)
    _scatter(make_fallen_log,    forest,                 80, min_spacing=5)
    _scatter(make_bush,          forest | open_,        110, min_spacing=4)
    _scatter(make_wild_mushroom, forest | {TileType.CAVE_FLOOR}, 55, min_spacing=6)
    _scatter(make_flower_patch,  {TileType.GRASS},       45, min_spacing=7)
    _scatter(make_tree,          forest | {TileType.GRASS}, 60, min_spacing=8)
    _scatter(make_hollow_tree,   forest,                 12, min_spacing=20)
    _scatter(make_reed_bed,      wet,                    35, min_spacing=6, extra=near_water)
    _scatter(make_herb_patch,    forest | {TileType.GRASS}, 40, min_spacing=10)

    from ..entities.items import make_stone, make_flint
    for _ in range(80):
        x = cx + rng.randint(-radius, radius)
        y = cy + rng.randint(-radius, radius)
        tile = world.get(x, y)
        if tile and tile.tile_type in (TileType.ROCKY, TileType.SAND, TileType.MOUNTAIN):
            world_state.add_entity(make_stone(x, y))
    for _ in range(30):
        x = cx + rng.randint(-radius, radius)
        y = cy + rng.randint(-radius, radius)
        tile = world.get(x, y)
        if tile and tile.tile_type in (TileType.ROCKY, TileType.MOUNTAIN):
            world_state.add_entity(make_flint(x, y))


def populate_animals(world_state, seed: int = None,
                     cx: int = 0, cy: int = 0, radius: int = 180):
    """Scatter animals in a radius around (cx, cy)."""
    from ..entities.animals import make_rabbit, make_deer, make_fox, make_bird

    rng = random.Random((seed or 0) + 7)
    world = world_state.world

    def place(make_fn, preferred, count):
        placed = 0
        attempts = 0
        while placed < count and attempts < count * 100:
            x = cx + rng.randint(-radius, radius)
            y = cy + rng.randint(-radius, radius)
            tile = world.get(x, y)
            if tile and tile.tile_type in preferred:
                world_state.add_entity(make_fn(x, y))
                placed += 1
            attempts += 1

    place(make_rabbit, {TileType.GRASS, TileType.WETLAND},          35)
    place(make_deer,   {TileType.FOREST, TileType.GRASS},            20)
    place(make_fox,    {TileType.GRASS, TileType.FOREST, TileType.ROCKY}, 15)
    place(make_bird,   {TileType.GRASS, TileType.SAND, TileType.WETLAND}, 25)
