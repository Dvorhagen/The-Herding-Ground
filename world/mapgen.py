"""
world/mapgen.py
Procedural map generation at 1 tile = 1 meter scale.
Map is 512x512 by default (~0.25 km²).

Terrain layers (applied in order):
  1. Grass base
  2. Large forest blobs with internal clearings
  3. Main river + sandy banks + wetland fringe
  4. Ponds (small lakes) with wetland edges
  5. Mountain ridgelines with rocky outcroppings/foothills
  6. Additional wetland pockets in low-lying areas
  7. Cave systems (CAVE_WALL pocket with CAVE_FLOOR interior)
  8. Paths: main cross, secondary, game trails through forest

populate_natural_objects(world_state, seed) scatters world objects
(boulders, bushes, logs, mushrooms, flowers) across appropriate tiles.
"""

import random
from .tiles import WorldMap, TileType


# ── Primitive shape helpers ───────────────────────────────────────────────────

def _fill_ellipse(world, cx, cy, rx, ry, tile_type, density=0.85, rng=random):
    for dy in range(-ry, ry + 1):
        for dx in range(-rx, rx + 1):
            if (dx / rx) ** 2 + (dy / ry) ** 2 <= 1.0:
                if rng.random() < density:
                    world.set(cx + dx, cy + dy, tile_type)


def _fill_circle(world, cx, cy, r, tile_type, density=0.90, rng=random):
    _fill_ellipse(world, cx, cy, r, r, tile_type, density, rng)


def _safe_set(world, x, y, tile_type, protect=(TileType.WATER, TileType.CAVE_WALL)):
    """Set a tile only if it isn't a protected type."""
    tile = world.get(x, y)
    if tile and tile.tile_type not in protect:
        world.set(x, y, tile_type)


# ── Terrain feature generators ────────────────────────────────────────────────

def _place_forests(world, rng):
    """4-7 large forest blobs with irregular clearings."""
    num_forests = rng.randint(4, 7)
    forest_centers = []
    for _ in range(num_forests):
        fx = rng.randint(world.width // 8, 7 * world.width // 8)
        fy = rng.randint(world.height // 8, 7 * world.height // 8)
        rx = rng.randint(45, 110)
        ry = rng.randint(45, 110)
        _fill_ellipse(world, fx, fy, rx, ry, TileType.FOREST, density=0.88, rng=rng)
        forest_centers.append((fx, fy, rx, ry))

        # Clearings: irregular meadows carved out of forest
        num_clearings = rng.randint(2, 5)
        for _ in range(num_clearings):
            cx = fx + rng.randint(-rx * 2 // 3, rx * 2 // 3)
            cy = fy + rng.randint(-ry * 2 // 3, ry * 2 // 3)
            cr = rng.randint(4, 18)
            # Slightly elongated clearings feel more natural
            crx = cr + rng.randint(-4, 8)
            cry = cr + rng.randint(-4, 8)
            _fill_ellipse(world, cx, cy, max(3, crx), max(3, cry),
                          TileType.GRASS, density=0.92, rng=rng)

    return forest_centers


def _place_river(world, rng):
    """One winding river from top to bottom, 3-7 tiles wide, with sandy banks and wetland fringe."""
    river_x = rng.randint(world.width // 4, 3 * world.width // 4)
    river_w = rng.randint(3, 5)

    river_path = []
    for y in range(world.height):
        if rng.random() > 0.65:
            river_x += rng.choice([-1, -1, 0, 0, 0, 1, 1])
            river_x = max(river_w + 4, min(world.width - river_w - 4, river_x))
        w = river_w + rng.randint(-1, 1)
        w = max(2, w)
        river_path.append((river_x, w))

        for dx in range(-w, w + 1):
            world.set(river_x + dx, y, TileType.WATER)
        # Sandy banks
        for bank in range(1, 4):
            for side in (-1, 1):
                bx = river_x + (w + bank) * side
                _safe_set(world, bx, y, TileType.SAND, protect=(TileType.WATER,))
        # Wetland fringe beyond sand
        for fringe in range(4, 7):
            for side in (-1, 1):
                bx = river_x + fringe * side
                if rng.random() < 0.4:
                    _safe_set(world, bx, y, TileType.WETLAND, protect=(TileType.WATER, TileType.SAND))

    return river_path


def _place_ponds(world, rng):
    """3-6 small ponds scattered across the map, each with wetland edges."""
    num_ponds = rng.randint(3, 6)
    for _ in range(num_ponds):
        px = rng.randint(world.width // 10, 9 * world.width // 10)
        py = rng.randint(world.height // 10, 9 * world.height // 10)
        r = rng.randint(5, 14)
        rx = r + rng.randint(-3, 5)
        ry = r + rng.randint(-3, 5)
        # Pond body
        _fill_ellipse(world, px, py, max(4, rx), max(4, ry),
                      TileType.WATER, density=0.92, rng=rng)
        # Sandy shore
        _fill_ellipse(world, px, py, rx + 3, ry + 3,
                      TileType.SAND, density=0.6, rng=rng)
        # Wetland fringe
        _fill_ellipse(world, px, py, rx + 6, ry + 6,
                      TileType.WETLAND, density=0.45, rng=rng)


def _place_mountains(world, rng):
    """1-3 ridgelines with rocky foothills."""
    num_ridges = rng.randint(1, 3)
    for _ in range(num_ridges):
        # Bias toward map edges so the center stays explorable
        edge = rng.choice(["east", "north", "south"])
        if edge == "east":
            mx = rng.randint(3 * world.width // 4, world.width - 30)
            my = rng.randint(world.height // 6, 5 * world.height // 6)
            direction = (0, 1)
        elif edge == "north":
            mx = rng.randint(world.width // 6, 5 * world.width // 6)
            my = rng.randint(10, world.height // 5)
            direction = (1, 0)
        else:
            mx = rng.randint(world.width // 6, 5 * world.width // 6)
            my = rng.randint(4 * world.height // 5, world.height - 10)
            direction = (1, 0)

        ridge_len = rng.randint(80, 220)
        ridge_w = rng.randint(3, 9)

        for step in range(ridge_len):
            for dw in range(-ridge_w, ridge_w + 1):
                wx = mx + dw * direction[1]
                wy = my + dw * direction[0]
                tile = world.get(wx, wy)
                if tile and tile.tile_type != TileType.WATER:
                    world.set(wx, wy, TileType.MOUNTAIN)
            # Rocky foothills on both sides of ridge
            for foot in range(ridge_w + 1, ridge_w + rng.randint(4, 10)):
                for side in (-1, 1):
                    fx = mx + foot * side * direction[1]
                    fy = my + foot * side * direction[0]
                    if rng.random() < 0.55:
                        _safe_set(world, fx, fy, TileType.ROCKY,
                                  protect=(TileType.WATER, TileType.MOUNTAIN))

            mx += direction[0] + (rng.randint(-1, 1) if rng.random() > 0.5 else 0)
            my += direction[1] + (rng.randint(-1, 1) if rng.random() > 0.5 else 0)
            mx = max(2, min(world.width - 3, mx))
            my = max(2, min(world.height - 3, my))


def _place_rocky_outcrops(world, rng):
    """Scattered rocky patches independent of mountain ridges — hilltops, scree fields."""
    num_outcrops = rng.randint(4, 9)
    for _ in range(num_outcrops):
        ox = rng.randint(20, world.width - 20)
        oy = rng.randint(20, world.height - 20)
        r = rng.randint(4, 14)
        _fill_ellipse(world, ox, oy, r, r + rng.randint(-3, 3),
                      TileType.ROCKY, density=0.65, rng=rng)


def _place_wetland_pockets(world, rng):
    """Additional wetland hollows in low-lying areas, independent of the river."""
    num_pockets = rng.randint(3, 7)
    for _ in range(num_pockets):
        wx = rng.randint(15, world.width - 15)
        wy = rng.randint(15, world.height - 15)
        rx = rng.randint(6, 20)
        ry = rng.randint(6, 20)
        _fill_ellipse(world, wx, wy, rx, ry, TileType.WETLAND, density=0.60, rng=rng)
        # Sometimes a small open-water centre
        if rng.random() < 0.35:
            _fill_ellipse(world, wx, wy, max(2, rx // 3), max(2, ry // 3),
                          TileType.WATER, density=0.80, rng=rng)


def _place_cave(world, cx, cy, rng):
    """
    Carve a small cave system: a CAVE_WALL shell with CAVE_FLOOR interior,
    facing entrance open to the south. Returns True if placed successfully.
    """
    w = rng.randint(8, 16)
    h = rng.randint(6, 12)
    # Bail if out of bounds
    if cx - w < 2 or cx + w >= world.width - 2 or cy - 2 < 2 or cy + h >= world.height - 2:
        return False
    # Shell of CAVE_WALL
    for dy in range(-2, h + 1):
        for dx in range(-w, w + 1):
            tile = world.get(cx + dx, cy + dy)
            if tile:
                world.set(cx + dx, cy + dy, TileType.CAVE_WALL)
    # Interior of CAVE_FLOOR
    for dy in range(0, h - 1):
        for dx in range(-w + 1, w):
            world.set(cx + dx, cy + dy, TileType.CAVE_FLOOR)
    # Entrance gap in south wall (3 tiles wide)
    for dx in range(-1, 2):
        world.set(cx + dx, cy + h, TileType.CAVE_FLOOR)
        world.set(cx + dx, cy + h - 1, TileType.CAVE_FLOOR)
    # A couple of internal pillars for interest
    for _ in range(rng.randint(1, 3)):
        px = cx + rng.randint(-w + 2, w - 2)
        py = cy + rng.randint(1, h - 3)
        world.set(px, py, TileType.CAVE_WALL)
    return True


def _place_caves(world, rng):
    """Place 1-3 cave systems, avoiding water and close to map edges."""
    num_caves = rng.randint(1, 3)
    for _ in range(num_caves):
        for attempt in range(20):
            cx = rng.randint(30, world.width - 30)
            cy = rng.randint(30, world.height - 30)
            tile = world.get(cx, cy)
            if tile and tile.tile_type not in (TileType.WATER, TileType.CAVE_WALL):
                if _place_cave(world, cx, cy, rng):
                    break


def _place_paths(world, rng):
    """Main E-W and N-S paths, plus 3-6 winding game trails through forest."""
    protect = (TileType.WATER, TileType.MOUNTAIN, TileType.CAVE_WALL)

    # Main east-west path near mid-map
    py = world.height // 2 + rng.randint(-30, 30)
    for x in range(world.width):
        _safe_set(world, x, py, TileType.PATH, protect)

    # Main north-south path, west side
    px = world.width // 3 + rng.randint(-20, 20)
    for y in range(world.height):
        _safe_set(world, px, y, TileType.PATH, protect)

    # Game trails — short winding paths between forest clearings
    num_trails = rng.randint(3, 6)
    for _ in range(num_trails):
        tx = rng.randint(world.width // 8, 7 * world.width // 8)
        ty = rng.randint(world.height // 8, 7 * world.height // 8)
        trail_len = rng.randint(30, 100)
        dx, dy = rng.choice([(1, 0), (0, 1), (1, 1), (-1, 1)])
        for step in range(trail_len):
            _safe_set(world, tx, ty, TileType.PATH, protect)
            if rng.random() > 0.75:
                dx += rng.randint(-1, 1)
                dy += rng.randint(-1, 1)
                dx = max(-1, min(1, dx))
                dy = max(-1, min(1, dy))
                if dx == 0 and dy == 0:
                    dy = 1
            tx = max(5, min(world.width - 5, tx + dx))
            ty = max(5, min(world.height - 5, ty + dy))


# ── Main generator ────────────────────────────────────────────────────────────

def generate_world(width: int = 512, height: int = 512, seed: int = None) -> WorldMap:
    """
    Generate a world at 1m scale. Feature order matters — later layers
    overwrite earlier ones (paths overwrite forest, etc.).
    """
    rng = random.Random(seed)

    world = WorldMap(width, height)

    _place_forests(world, rng)
    _place_river(world, rng)
    _place_ponds(world, rng)
    _place_mountains(world, rng)
    _place_rocky_outcrops(world, rng)
    _place_wetland_pockets(world, rng)
    _place_caves(world, rng)
    _place_paths(world, rng)

    return world


# ── Spawn finder ──────────────────────────────────────────────────────────────

def find_spawn(world: WorldMap) -> tuple[int, int]:
    """
    Find the best spawn point near the centre of the map.
    Prefers path intersections, then any path tile, then any passable tile.
    Ranks all candidates by Manhattan distance from the map centre.
    """
    cx, cy = world.width // 2, world.height // 2
    margin = 15

    path_intersections = []
    path_tiles = []
    passable_tiles = []

    for y in range(margin, world.height - margin):
        for x in range(margin, world.width - margin):
            tile = world.get(x, y)
            if not tile:
                continue
            dist = abs(x - cx) + abs(y - cy)
            if tile.tile_type == TileType.PATH:
                neighbors = [world.get(x + dx, y + dy)
                             for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))]
                cross = sum(1 for t in neighbors if t and t.tile_type == TileType.PATH)
                if cross >= 2:
                    path_intersections.append((dist, x, y))
                else:
                    path_tiles.append((dist, x, y))
            elif tile.tile_type not in (TileType.WATER, TileType.MOUNTAIN, TileType.CAVE_WALL):
                passable_tiles.append((dist, x, y))

    for candidates in (path_intersections, path_tiles, passable_tiles):
        if candidates:
            candidates.sort()
            return candidates[0][1], candidates[0][2]

    return cx, cy


# ── Natural object population ─────────────────────────────────────────────────

def populate_natural_objects(world_state, seed: int = None):
    """
    Scatter natural world objects across the map based on tile type.
    Call this after WorldState is created, before the game loop starts.
    """
    from .objects import (make_boulder, make_bush, make_fallen_log,
                          make_wild_mushroom, make_flower_patch)

    rng = random.Random(seed)
    world = world_state.world
    W, H = world.width, world.height

    def _scatter(make_fn, allowed_tiles, count, min_spacing=6, extra=None):
        """Place `count` objects of the given type on allowed tile types."""
        placed = []
        attempts = 0
        while len(placed) < count and attempts < count * 150:
            x = rng.randint(8, W - 8)
            y = rng.randint(8, H - 8)
            tile = world.get(x, y)
            if not tile or tile.tile_type not in allowed_tiles:
                attempts += 1
                continue
            if any(abs(x - px) < min_spacing and abs(y - py) < min_spacing
                   for px, py in placed):
                attempts += 1
                continue
            if extra and not extra(x, y):
                attempts += 1
                continue
            world_state.add_object(make_fn(x, y))
            placed.append((x, y))
            attempts += 1

    forest   = {TileType.FOREST}
    open_    = {TileType.GRASS, TileType.WETLAND}
    rocky    = {TileType.ROCKY, TileType.MOUNTAIN}
    anywhere = {TileType.GRASS, TileType.FOREST, TileType.ROCKY, TileType.SAND}
    wet      = {TileType.WETLAND, TileType.SAND}

    def near_water(x, y):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                t = world.get(x + dx, y + dy)
                if t and t.tile_type == TileType.WATER:
                    return True
        return False

    # Boulders — rocky terrain and lone outliers in open ground
    _scatter(make_boulder, rocky,                      40, min_spacing=8)
    _scatter(make_boulder, {TileType.GRASS},           10, min_spacing=25)

    # Fallen logs — forest floor
    _scatter(make_fallen_log, forest,                  80, min_spacing=5)

    # Bushes — forest edges and open grassland
    _scatter(make_bush, forest | open_,               110, min_spacing=4)

    # Wild mushrooms — shady forest and cave floors
    _scatter(make_wild_mushroom,
             forest | {TileType.CAVE_FLOOR},            55, min_spacing=6)

    # Flower patches — open clearings and grassland
    _scatter(make_flower_patch, {TileType.GRASS},       45, min_spacing=7)

    # Scatter some loose stones as ground items near rocky areas
    from ..entities.items import make_stone
    for _ in range(60):
        x = rng.randint(8, W - 8)
        y = rng.randint(8, H - 8)
        tile = world.get(x, y)
        if tile and tile.tile_type in (TileType.ROCKY, TileType.SAND, TileType.MOUNTAIN):
            world_state.add_entity(make_stone(x, y))
