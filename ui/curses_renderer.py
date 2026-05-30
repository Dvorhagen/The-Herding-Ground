"""
ui/curses_renderer.py
Terminal renderer using curses. Runs over SSH without X forwarding.
Same interface as the pygame Renderer -- swap one for the other in main.py.

Layout:
  Left: map viewport (fills most of terminal)
  Right panel: status, thought, message log
  Bottom bar: controls reminder
"""

import curses
import textwrap
from ..world.tiles import TileType, TILE_PROPERTIES


# Tile symbol -> curses color pair mapping
# We use 4 color pairs: dim, normal, bright, highlight
PAIR_DIM       = 1
PAIR_NORMAL    = 2
PAIR_BRIGHT    = 3
PAIR_HIGHLIGHT = 4
PAIR_NEMO      = 5
PAIR_ITEM      = 6
PAIR_WARNING   = 7

# Map tile types to color pairs
TILE_COLORS = {
    TileType.GRASS:      PAIR_NORMAL,
    TileType.FOREST:     PAIR_DIM,
    TileType.WATER:      PAIR_DIM,
    TileType.MOUNTAIN:   PAIR_DIM,
    TileType.SAND:       PAIR_NORMAL,
    TileType.CAVE_FLOOR: PAIR_DIM,
    TileType.CAVE_WALL:  PAIR_DIM,
    TileType.PATH:       PAIR_BRIGHT,
}


class CursesRenderer:
    """
    Terminal renderer. Same public interface as the pygame Renderer:
      - add_message(str)
      - center_on(x, y)
      - draw(world_state)
      - last_thought (str attribute)
      - get_input() -> returns keypress or None
    """

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.last_thought = ""
        self.messages = []
        self.max_messages = 50
        self.view_x = 0
        self.view_y = 0
        self.tick_delay_idx = 3   # set by main.py
        self.tick_delay = 1.0
        self.stepped = False
        self.show_los = False

        self._setup_curses()

    def _setup_curses(self):
        curses.curs_set(0)          # hide cursor
        curses.noecho()
        self.stdscr.nodelay(True)   # non-blocking input
        self.stdscr.keypad(True)

        # Initialize color pairs (green phosphor on black)
        curses.start_color()
        curses.use_default_colors()
        # pair number, foreground, background (-1 = terminal default)
        curses.init_pair(PAIR_DIM,       curses.COLOR_GREEN,  -1)
        curses.init_pair(PAIR_NORMAL,    curses.COLOR_GREEN,  -1)
        curses.init_pair(PAIR_BRIGHT,    curses.COLOR_GREEN,  -1)
        curses.init_pair(PAIR_HIGHLIGHT, curses.COLOR_WHITE,  -1)
        curses.init_pair(PAIR_NEMO,      curses.COLOR_WHITE,  -1)
        curses.init_pair(PAIR_ITEM,      curses.COLOR_YELLOW, -1)
        curses.init_pair(PAIR_WARNING,   curses.COLOR_RED,    -1)

    def add_message(self, msg: str):
        self.messages.append(msg)
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def center_on(self, x: int, y: int):
        h, w = self.stdscr.getmaxyx()
        panel_w = min(40, w // 3)
        map_w = w - panel_w
        map_h = h - 1  # leave bottom bar
        self.view_x = max(0, x - map_w // 2)
        self.view_y = max(0, y - map_h // 2)

    def draw(self, world_state):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()

        panel_w = min(42, w // 3)
        map_w = w - panel_w - 1  # -1 for divider
        map_h = h - 1            # -1 for bottom bar

        self._draw_map(world_state, map_w, map_h)
        self._draw_divider(map_w, map_h)
        self._draw_panel(world_state, map_w + 1, panel_w, map_h)
        self._draw_bottom_bar(h - 1, w)

        try:
            self.stdscr.refresh()
        except curses.error:
            pass

    def _draw_map(self, world_state, map_w, map_h):
        world = world_state.world
        nemo = world_state.nemo

        for row in range(map_h):
            for col in range(map_w):
                wx = col + self.view_x
                wy = row + self.view_y

                if wx == nemo.x and wy == nemo.y:
                    self._put(row, col, "@",
                              curses.color_pair(PAIR_NEMO) | curses.A_BOLD)
                    continue

                occluded = self.show_los and (wx, wy) not in world_state.visible_tiles

                # Check for items at this position
                items_here = world_state.get_items_at(wx, wy)
                if items_here and not occluded:
                    self._put(row, col, items_here[0].symbol,
                              curses.color_pair(PAIR_ITEM))
                    continue

                tile = world.get(wx, wy)
                if tile is None:
                    self._put(row, col, " ", curses.color_pair(PAIR_DIM))
                elif occluded:
                    self._put(row, col, tile.props.symbol,
                              curses.color_pair(PAIR_DIM) | curses.A_DIM)
                else:
                    pair = TILE_COLORS.get(tile.tile_type, PAIR_NORMAL)
                    attr = curses.color_pair(pair)
                    if tile.tile_type == TileType.PATH:
                        attr |= curses.A_BOLD
                    elif tile.tile_type == TileType.FOREST:
                        attr |= curses.A_DIM
                    self._put(row, col, tile.props.symbol, attr)

    def _draw_divider(self, map_w, map_h):
        for row in range(map_h):
            self._put(row, map_w, "│", curses.color_pair(PAIR_DIM))

    def _draw_panel(self, world_state, px, panel_w, map_h):
        nemo = world_state.nemo
        row = 0

        # Title
        self._put(row, px, "// NEMO",
                  curses.color_pair(PAIR_HIGHLIGHT) | curses.A_BOLD)
        row += 1
        self._put(row, px, "─" * (panel_w - 1), curses.color_pair(PAIR_DIM))
        row += 1

        # Status
        self._panel_text(row, px, panel_w,
                         f"POS  : ({nemo.x},{nemo.y})  T:{world_state.tick}")
        row += 1

        status = nemo.status.describe()
        # Colour warning if hungry/tired
        warn = nemo.status.hunger < 20 or nemo.status.fatigue > 80
        attr = curses.color_pair(PAIR_WARNING) if warn else curses.color_pair(PAIR_NORMAL)
        self._panel_text(row, px, panel_w, f"STATE: {status}", attr)
        row += 1

        inv = nemo.describe_inventory()
        self._panel_text(row, px, panel_w, f"CARRY: {inv}")
        row += 1

        # Speed bar: 7 segments, filled up to current index
        n = 7
        filled = self.tick_delay_idx + 1
        bar = "█" * filled + "░" * (n - filled)
        if self.stepped:
            spd_str = f"SPD : [{bar}] STEP"
            attr = curses.color_pair(PAIR_WARNING) | curses.A_BOLD
        else:
            spd_str = f"SPD : [{bar}] {self.tick_delay}s"
            attr = curses.color_pair(PAIR_NORMAL)
        self._panel_text(row, px, panel_w, spd_str, attr)
        row += 1

        self._put(row, px, "─" * (panel_w - 1), curses.color_pair(PAIR_DIM))
        row += 1

        # Thought
        self._put(row, px, "THOUGHT:",
                  curses.color_pair(PAIR_DIM))
        row += 1
        if self.last_thought:
            wrapped = textwrap.wrap(self.last_thought, panel_w - 2)
            for line in wrapped[:3]:  # max 3 lines
                self._panel_text(row, px, panel_w, line,
                                 curses.color_pair(PAIR_HIGHLIGHT))
                row += 1
        else:
            row += 1

        self._put(row, px, "─" * (panel_w - 1), curses.color_pair(PAIR_DIM))
        row += 1

        # Message log
        self._put(row, px, "LOG:",
                  curses.color_pair(PAIR_DIM))
        row += 1

        available = map_h - row
        visible = self.messages[-available:] if available > 0 else []
        for i, msg in enumerate(visible):
            # Fade older messages
            age = len(visible) - i
            attr = curses.color_pair(PAIR_DIM) if age > 5 else curses.color_pair(PAIR_NORMAL)
            self._panel_text(row, px, panel_w, msg, attr)
            row += 1
            if row >= map_h:
                break

    def _draw_bottom_bar(self, row, w):
        bar = " TAB:mode  arrows/wasd:move  p:pickup  e:examine  [:faster  ]:slower  SPC:step  v:LOS  q:quit "
        bar = bar[:w - 1].ljust(w - 1)
        try:
            self.stdscr.addstr(row, 0, bar,
                               curses.color_pair(PAIR_DIM) | curses.A_REVERSE)
        except curses.error:
            pass

    def get_input(self):
        """Non-blocking input. Returns curses key constant or None."""
        try:
            return self.stdscr.getch()
        except curses.error:
            return -1

    def _put(self, row, col, char, attr=0):
        """Safe character put -- silently ignores out-of-bounds."""
        try:
            self.stdscr.addstr(row, col, char, attr)
        except curses.error:
            pass

    def _panel_text(self, row, px, panel_w, text, attr=None):
        """Write text in the panel, truncated to panel width."""
        if attr is None:
            attr = curses.color_pair(PAIR_NORMAL)
        text = text[:panel_w - 1]
        try:
            self.stdscr.addstr(row, px, text, attr)
        except curses.error:
            pass
