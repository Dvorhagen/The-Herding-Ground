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
PAIR_DIM       = 1
PAIR_NORMAL    = 2
PAIR_BRIGHT    = 3
PAIR_HIGHLIGHT = 4
PAIR_MORIARTY  = 5
PAIR_ITEM      = 6
PAIR_WARNING   = 7
PAIR_PLAYER    = 8   # amber — Aaron's avatar

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
        self.reasoning_stream = ""   # live CoT tokens; set by main.py callback
        self.messages = []
        self.max_messages = 50
        self.view_x = 0
        self.view_y = 0
        self.tick_delay_idx = 3   # set by main.py
        self.tick_delay = 1.0
        self.stepped = False
        self.show_los = False
        self.show_help = False
        self.control_mode_label = "MORIARTY"   # updated by main.py
        self.speech_bubbles = {}   # actor_name.lower() -> {text, expires}
        # Non-blocking text input state (integrated into main loop, not modal)
        self.text_input_active = False
        self.text_input_prompt = ""
        self.text_input_buffer = []
        self.text_input_mode = ""   # "god_inject" | "player_talk"

        self._help_lines = [
            "  KEY REFERENCE",
            "  " + "─" * 30,
            "  TAB        drop-in / return to Moriarty",
            "  [MORIARTY MODE]",
            "  [ / ]      tick speed",
            "  SPACE      step mode on/off",
            "  .          advance one step",
            "  `          cycle prompt style",
            "  [GOD MODE]",
            "  arrows     pan camera",
            "  m          jump to Moriarty",
            "  t          inject [ENVIRONMENT]",
            "  [PLAYER MODE]",
            "  arrows     move your avatar",
            "  t          talk to Moriarty",
            "  [ALWAYS]",
            "  v          LOS overlay",
            "  ?          this help",
            "  q          quit",
            "  " + "─" * 30,
            "  any key to close",
        ]

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
        curses.init_pair(PAIR_MORIARTY,  curses.COLOR_WHITE,  -1)
        curses.init_pair(PAIR_ITEM,      curses.COLOR_YELLOW, -1)
        curses.init_pair(PAIR_WARNING,   curses.COLOR_RED,    -1)
        curses.init_pair(PAIR_PLAYER,    curses.COLOR_YELLOW, -1)

    def add_message(self, msg: str):
        self.messages.append(msg)
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def center_on(self, x: int, y: int):
        h, w = self.stdscr.getmaxyx()
        panel_w = min(40, w // 3)
        map_w = w - panel_w
        map_h = h - 1  # leave bottom bar
        self.view_x = x - map_w // 2
        self.view_y = y - map_h // 2

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

        if self.show_help:
            self._draw_help()

        try:
            self.stdscr.refresh()
        except curses.error:
            pass

    def _draw_map(self, world_state, map_w, map_h):
        world = world_state.world
        moriarty = world_state.moriarty

        # Pre-index entities by tile position so we don't scan all entities per tile
        player_at = {}    # (x,y) -> PlayerEntity
        creature_at = {}  # (x,y) -> first non-item, non-player entity (animals etc.)
        for e in world_state.entities:
            et_name = getattr(getattr(e, 'entity_type', None), 'name', '')
            pos = (e.x, e.y)
            if et_name == 'PLAYER':
                player_at[pos] = e
            elif not hasattr(e, 'item_type') and pos not in creature_at:
                creature_at[pos] = e

        for row in range(map_h):
            for col in range(map_w):
                wx = col + self.view_x
                wy = row + self.view_y
                pos = (wx, wy)

                # 1. Moriarty — always on top
                if wx == moriarty.x and wy == moriarty.y:
                    self._put(row, col, "@",
                              curses.color_pair(PAIR_MORIARTY) | curses.A_BOLD)
                    continue

                # 2. Player avatar (amber @)
                if pos in player_at:
                    e = player_at[pos]
                    self._put(row, col, e.symbol,
                              curses.color_pair(PAIR_PLAYER) | curses.A_BOLD)
                    continue

                occluded = self.show_los and pos not in world_state.visible_tiles

                # 3. World objects (campfire, trees, boulders, etc.)
                objects_here = world_state.get_objects_at(wx, wy)
                if objects_here and not occluded:
                    self._put(row, col, objects_here[0].symbol,
                              curses.color_pair(PAIR_ITEM) | curses.A_BOLD)
                    continue

                # 4. Items on the ground
                items_here = world_state.get_items_at(wx, wy)
                if items_here and not occluded:
                    self._put(row, col, items_here[0].symbol,
                              curses.color_pair(PAIR_ITEM))
                    continue

                # 5. Creatures / animals / NPCs
                if pos in creature_at and not occluded:
                    self._put(row, col, creature_at[pos].symbol,
                              curses.color_pair(PAIR_NORMAL))
                    continue

                # 6. Tile
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

        # Speech bubbles — drawn on top of everything, following entity live position
        self._draw_speech_bubbles(world_state, map_w, map_h)

    def _draw_divider(self, map_w, map_h):
        for row in range(map_h):
            self._put(row, map_w, "│", curses.color_pair(PAIR_DIM))

    def _draw_panel(self, world_state, px, panel_w, map_h):
        moriarty = world_state.moriarty
        row = 0

        # Title + control mode
        self._put(row, px, "// MORIARTY",
                  curses.color_pair(PAIR_HIGHLIGHT) | curses.A_BOLD)
        row += 1
        self._put(row, px, "─" * (panel_w - 1), curses.color_pair(PAIR_DIM))
        row += 1

        # Control mode indicator
        label = self.control_mode_label
        if label == "MORIARTY":
            mode_attr = curses.color_pair(PAIR_HIGHLIGHT)
        elif label == "GOD":
            mode_attr = curses.color_pair(PAIR_WARNING) | curses.A_BOLD
        elif label == "PLAYER":
            mode_attr = curses.color_pair(PAIR_PLAYER) | curses.A_BOLD
        else:
            mode_attr = curses.color_pair(PAIR_WARNING) | curses.A_BOLD
        self._panel_text(row, px, panel_w, f"MODE : {label}", mode_attr)
        row += 1

        # Status
        self._panel_text(row, px, panel_w,
                         f"POS  : ({moriarty.x},{moriarty.y})  T:{world_state.tick}")
        row += 1

        status = moriarty.status.describe()
        # Colour warning if hungry/tired
        warn = moriarty.status.hunger < 20 or moriarty.status.fatigue > 80
        attr = curses.color_pair(PAIR_WARNING) if warn else curses.color_pair(PAIR_NORMAL)
        self._panel_text(row, px, panel_w, f"STATE: {status}", attr)
        row += 1

        inv = moriarty.describe_inventory()
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

        # Thought / live reasoning stream
        if self.reasoning_stream:
            self._put(row, px, "REASONING:",
                      curses.color_pair(PAIR_DIM) | curses.A_DIM)
            row += 1
            tail = self.reasoning_stream[-200:]
            if len(self.reasoning_stream) > 200:
                tail = tail[tail.find(" ") + 1:]
            wrapped = textwrap.wrap(tail, panel_w - 2)
            for line in wrapped[-4:]:   # show last 4 lines of reasoning
                self._panel_text(row, px, panel_w, line,
                                 curses.color_pair(PAIR_DIM))
                row += 1
        else:
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
        if self.text_input_active:
            prompt = f" {self.text_input_prompt}: "
            text = "".join(self.text_input_buffer)
            bar = (prompt + text + "_")[:w - 1].ljust(w - 1)
            try:
                self.stdscr.addstr(row, 0, bar,
                                   curses.color_pair(PAIR_PLAYER) | curses.A_BOLD)
            except curses.error:
                pass
            return

        label = self.control_mode_label
        if label == "MORIARTY":
            bar = " TAB:drop-in  [:lag-  ]:lag+  SPC:step  .:advance  v:LOS  `:style  ?:help  q:quit "
        elif label == "DROP-IN?":
            bar = " G:god observer  P:player character  ESC:cancel "
        elif label == "GOD":
            bar = " TAB:return  arrows:pan  m:jump to Mo  t:inject  v:LOS  q:quit "
        elif label == "PLAYER":
            bar = " TAB:return  arrows:move  t:talk  p:pickup  .:wait  v:LOS  q:quit "
        else:
            bar = " TAB:mode  q:quit "
        bar = bar[:w - 1].ljust(w - 1)
        try:
            self.stdscr.addstr(row, 0, bar,
                               curses.color_pair(PAIR_DIM) | curses.A_REVERSE)
        except curses.error:
            pass

    def _draw_help(self):
        h, w = self.stdscr.getmaxyx()
        box_h = len(self._help_lines) + 2
        box_w = 33
        by = max(0, (h - box_h) // 2)
        bx = max(0, (w - box_w) // 2)
        for i, line in enumerate(self._help_lines):
            attr = (curses.color_pair(PAIR_HIGHLIGHT) | curses.A_BOLD
                    if i == 0 else curses.color_pair(PAIR_NORMAL))
            self._put(by + 1 + i, bx, line[:box_w - 1], attr)

    def get_input(self):
        """Non-blocking input. Returns curses key constant or None."""
        try:
            return self.stdscr.getch()
        except curses.error:
            return -1

    def add_speech_bubble(self, actor_name: str, text: str, duration: float = 7.0):
        """Register a speech bubble. Follows the named actor's live position."""
        import time
        if len(text) > 200:
            text = text[:197] + "..."
        self.speech_bubbles[actor_name.lower()] = {
            "text": text,
            "expires": time.monotonic() + duration,
        }

    def _draw_speech_bubbles(self, world_state, map_w: int, map_h: int):
        """Draw floating speech text above each speaking entity."""
        import time
        now = time.monotonic()
        expired = [n for n, b in self.speech_bubbles.items() if b["expires"] <= now]
        for n in expired:
            del self.speech_bubbles[n]

        for name, bubble in self.speech_bubbles.items():
            # Resolve current world position of the speaker
            mo = world_state.moriarty
            if name in (mo.name.lower(), "moriarty"):
                ex, ey = mo.x, mo.y
            else:
                found = next(
                    (e for e in world_state.entities if e.name.lower() == name),
                    None,
                )
                if not found:
                    continue
                ex, ey = found.x, found.y

            # Convert to viewport coordinates
            sc = ex - self.view_x   # screen column (speaker's @)
            sr = ey - self.view_y   # screen row

            # Draw one row above; if that's off-screen, draw one below
            bubble_row = sr - 1 if sr > 0 else sr + 1
            if bubble_row < 0 or bubble_row >= map_h:
                continue

            full_text = f'"{bubble["text"]}"'
            # Word-wrap to at most map_w - 2 chars
            wrap_w = min(60, map_w - 2)
            words = full_text.split()
            wrapped_lines = []
            cur = ""
            for word in words:
                if len(cur) + len(word) + 1 <= wrap_w:
                    cur = cur + (" " if cur else "") + word
                else:
                    if cur:
                        wrapped_lines.append(cur)
                    cur = word
            if cur:
                wrapped_lines.append(cur)

            for li, text in enumerate(wrapped_lines):
                row_y = bubble_row - li  # stack upward from the bubble_row
                if row_y < 0 or row_y >= map_h:
                    continue
                start_col = sc - len(text) // 2
                if start_col < 0:
                    start_col = 0
                if start_col + len(text) > map_w:
                    text = text[:map_w - start_col]
                self._put(row_y, start_col, text,
                          curses.color_pair(PAIR_HIGHLIGHT) | curses.A_BOLD)

    def get_text_input(self, prompt: str) -> str:
        """
        Blocking modal text input rendered in the bottom bar.
        Uses a manual getch loop — more reliable than getstr across terminals.
        Returns the entered string, or "" if cancelled with ESC.
        Mo's AI thread continues in background; result is processed on next loop.
        """
        import time as _t
        h, w = self.stdscr.getmaxyx()
        bar_row = h - 1
        prompt_str = f" {prompt}: "
        max_input = max(10, w - len(prompt_str) - 3)

        curses.curs_set(1)
        self.stdscr.nodelay(False)   # switch to blocking input

        chars = []
        cancelled = False
        while True:
            # Redraw the input bar every keystroke
            display = prompt_str + "".join(chars) + "_"
            display = display[:w - 1].ljust(w - 1)
            try:
                self.stdscr.addstr(bar_row, 0, display,
                                   curses.color_pair(PAIR_HIGHLIGHT) | curses.A_REVERSE)
                cursor_col = min(len(prompt_str) + len(chars), w - 2)
                self.stdscr.move(bar_row, cursor_col)
            except curses.error:
                pass
            self.stdscr.refresh()

            ch = self.stdscr.getch()

            if ch in (10, 13, curses.KEY_ENTER):   # Enter — submit
                break
            elif ch == 27:                           # ESC — cancel
                cancelled = True
                break
            elif ch in (8, 127, curses.KEY_BACKSPACE):
                if chars:
                    chars.pop()
            elif 32 <= ch < 127 and len(chars) < max_input:
                chars.append(chr(ch))

        curses.curs_set(0)
        self.stdscr.nodelay(True)   # restore non-blocking

        return "" if cancelled else "".join(chars)

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
