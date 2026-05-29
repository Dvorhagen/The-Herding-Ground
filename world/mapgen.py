"""
world/mapgen.py
Procedural map generation at 1 tile = 1 meter scale.
Map is 512x512 by default. Features are sized accordingly:
  - Forests: large contiguous blobs, 50-200m across
  - River: 3-8 tiles wide, winding north-to-south
  - Mountains: long ridgelines
  - Meadows: open grassland clearings within forest
  - Paths: worn trails connecting features
"""

import random
from .tiles import WorldMap, TileType


def _fill_ellipse(world, cx, cy, rx, ry, tile_type, density=0.85):
    """Fill an elliptical region with a tile type, with some randomness."""
    for dy in range(-ry, ry + 1):
        for dx in range(-rx, rx + 1):
            if (dx/rx)**2 + (dy/ry)**2 <= 1.0:
                if random.random() < density:
                    world.set(cx + dx, cy + dy, tile_type)


def generate_world(width: int = 512, height: int = 512, seed: int = None) -> WorldMap:
    """
    Generates a world at 1m scale.
    At 512x512 this is roughly 0.25 km² — a small valley or forest clearing
    with room to explore for a long time on foot.
    """
    if seed is not None:
        random.seed(seed)

    world = WorldMap(width, height)

    # --- Base layer: grass everywhere ---
    # (already grass by default)

    # --- Large forest regions ---
    # 4-6 major forest zones, each 80-200m across
    num_forests = random.randint(4, 6)
    forest_centers = []
    for _ in range(num_forests):
        fx = random.randint(width // 6, 5 * width // 6)
        fy = random.randint(height // 6, 5 * height // 6)
        rx = random.randint(40, 100)
        ry = random.randint(40, 100)
        _fill_ellipse(world, fx, fy, rx, ry, TileType.FOREST, density=0.88)
        forest_centers.append((fx, fy))

        # Clearings within forest (meadows)
        num_clearings = random.randint(1, 3)
        for _ in range(num_clearings):
            cx = fx + random.randint(-rx//2, rx//2)
            cy = fy + random.randint(-ry//2, ry//2)
            cr = random.randint(5, 20)
            _fill_ellipse(world, cx, cy, cr, cr, TileType.GRASS, density=0.95)

    # --- River ---
    # Starts at top of map, winds to bottom, 3-8 tiles wide
    river_x = random.randint(width // 4, 3 * width // 4)
    river_width_base = random.randint(3, 6)

    for y in range(height):
        # Meander
        if random.random() > 0.7:
            river_x += random.choice([-1, -1, 0, 0, 0, 1, 1])
            river_x = max(river_width_base + 2, min(width - river_width_base - 2, river_x))

        # Width varies slightly
        w = river_width_base + random.randint(-1, 1)
        w = max(2, w)

        for dx in range(-w, w + 1):
            world.set(river_x + dx, y, TileType.WATER)

        # Sandy banks (2-3 tiles each side)
        for bank in range(1, 4):
            for side in [-1, 1]:
                bx = river_x + (w + bank) * side
                tile = world.get(bx, y)
                if tile and tile.tile_type not in (TileType.WATER,):
                    world.set(bx, y, TileType.SAND)

    # --- Mountain ridgelines ---
    num_ridges = random.randint(1, 2)
    for _ in range(num_ridges):
        # Start point on an edge-ish area
        mx = random.randint(3 * width // 4, width - 30)
        my = random.randint(height // 6, height // 3)
        ridge_len = random.randint(80, 200)
        ridge_width = random.randint(3, 8)

        for step in range(ridge_len):
            for dw in range(-ridge_width, ridge_width + 1):
                wx = mx + dw
                tile = world.get(wx, my)
                if tile and tile.tile_type != TileType.WATER:
                    world.set(wx, my, TileType.MOUNTAIN)
            my += 1
            if random.random() > 0.6:
                mx += random.choice([-1, 0, 0, 1])
            mx = max(2, min(width - 3, mx))
            my = max(2, min(height - 3, my))

    # --- Paths ---
    # Main east-west path roughly mid-map
    py = height // 2 + random.randint(-20, 20)
    for x in range(width):
        tile = world.get(x, py)
        if tile and tile.tile_type not in (TileType.WATER, TileType.MOUNTAIN):
            world.set(x, py, TileType.PATH)

    # Secondary north-south path, west of river
    river_approx = width // 3
    px = river_approx - random.randint(15, 40)
    for y in range(height):
        tile = world.get(px, y)
        if tile and tile.tile_type not in (TileType.WATER, TileType.MOUNTAIN):
            world.set(px, y, TileType.PATH)

    return world


def find_spawn(world: WorldMap) -> tuple[int, int]:
    """
    Find a good spawn point — prefer path intersections,
    then any path tile, then any passable tile.
    Avoid map edges (stay at least 15 tiles in).
    """
    margin = 15
    # Path intersection
    for y in range(margin, world.height - margin):
        for x in range(margin, world.width - margin):
            tile = world.get(x, y)
            if tile and tile.tile_type == TileType.PATH:
                # Check for cross-path nearby
                neighbors = [world.get(x+dx, y+dy)
                             for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)]]
                if sum(1 for t in neighbors if t and t.tile_type == TileType.PATH) >= 2:
                    return x, y

    # Any path tile away from edges
    for y in range(margin, world.height - margin):
        for x in range(margin, world.width - margin):
            tile = world.get(x, y)
            if tile and tile.tile_type == TileType.PATH:
                return x, y

    # Any passable tile
    for y in range(margin, world.height - margin):
        for x in range(margin, world.width - margin):
            if world.is_passable(x, y):
                return x, y

    return margin, margin
