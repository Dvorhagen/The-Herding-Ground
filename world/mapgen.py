"""
world/mapgen.py
Procedural map generation. Simple and readable -- this is not the interesting part.
Generates a starter world for Nemo to explore.
"""

import random
from .tiles import WorldMap, TileType


def generate_world(width: int = 40, height: int = 40, seed: int = None) -> WorldMap:
    """
    Generates a simple world with:
    - Grass base
    - Forest clusters
    - A river
    - Some mountain ridges
    - Sandy beach near water
    - A few paths
    """
    if seed is not None:
        random.seed(seed)

    world = WorldMap(width, height)

    # --- Forest clusters ---
    num_forests = 8
    for _ in range(num_forests):
        fx, fy = random.randint(2, width - 3), random.randint(2, height - 3)
        size = random.randint(3, 8)
        for dy in range(-size, size + 1):
            for dx in range(-size, size + 1):
                if dx*dx + dy*dy <= size*size and random.random() > 0.3:
                    world.set(fx + dx, fy + dy, TileType.FOREST)

    # --- River (vertical-ish) ---
    rx = width // 3
    for y in range(height):
        world.set(rx, y, TileType.WATER)
        if random.random() > 0.6:
            rx += random.choice([-1, 0, 0, 1])
            rx = max(2, min(width - 3, rx))
        # Sandy banks
        for bank_dx in [-1, 1]:
            bx = rx + bank_dx
            if world.get(bx, y) and world.get(bx, y).tile_type != TileType.WATER:
                world.set(bx, y, TileType.SAND)

    # --- Mountain ridge ---
    mx, my = random.randint(width//2, width - 5), 2
    for _ in range(height - 4):
        world.set(mx, my, TileType.MOUNTAIN)
        my += 1
        if random.random() > 0.7:
            mx += random.choice([-1, 0, 1])
            mx = max(width//2, min(width - 3, mx))

    # --- Paths ---
    # Horizontal path across the map
    py = height // 2
    for x in range(width):
        tile = world.get(x, py)
        if tile and tile.passable:
            world.set(x, py, TileType.PATH)

    return world


def find_spawn(world: WorldMap) -> tuple[int, int]:
    """Find a passable spawn point, preferably on a path or grass."""
    # Try path first
    for y in range(world.height):
        for x in range(world.width):
            tile = world.get(x, y)
            if tile and tile.tile_type == TileType.PATH:
                return x, y
    # Fall back to any passable tile
    for y in range(world.height):
        for x in range(world.width):
            if world.is_passable(x, y):
                return x, y
    return 0, 0
