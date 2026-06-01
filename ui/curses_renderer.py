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
import unicodedata
from ..world.tiles import TileType, TILE_PROPERTIES


def _safe(text: str, max_len: int = 0) -> str:
    """
    Sanitise text for curses output.
    - Strips control characters (including ANSI escapes).
    - Replaces non-ASCII with ASCII look-alikes or '?'.
    - Curses addstr can crash on multi-byte chars on narrow/mobile terminals.
    """
    replacements = {
        "│": "|",   # │ box-drawing
        "-": "-",   # -
        "═": "=",   # ═
        "█": "#",   # █ full block
        "░": ".",   # ░ light shade
        "▒": ":",   # ▒ medium shade
        "▓": "+",   # ▓ dark shade
        "╬": "+",   # ╬
        "╔": "+",   # ╔
        "╗": "+",   # ╗
        "╚": "+",   # ╚
        "╝": "+",   # ╝
        "╠": "+",   # ╠
        "╣": "+",   # ╣
        "╦": "+",   # ╦
        "╩": "+",   # ╩
        "◀": "<",   # ◀
        "—": "-",   # em dash
        "–": "-",   # en dash
        "‘": "'",   # left single quote
        "’": "'",   # right single quote
        "“": '"',   # left double quote
        "”": '"',   # right double quote
        "…": "...", # ellipsis
        "°": "°",   # degree (usually safe, but replace to be sure)
        "✓": "v",   # ✓ check mark
        "✗": "x",   # ✗ ballot x
        "●": "*",   # ● bullet
    }
    out = []
    for ch in text:
        if ch in replacements:
            out.append(replacements[ch])
        elif ord(ch) < 32 or ord(ch) == 127:
            pass   # strip control chars
        elif ord(ch) > 127:
            # Try to transliterate; fall back to ?
            try:
                norm = unicodedata.normalize("NFKD", ch)
                ascii_ch = norm.encode("ascii", errors="ignore").decode("ascii")
                out.append(ascii_ch if ascii_ch else "?")
            except Exception:
                out.append("?")
        else:
            out.append(ch)
    result = "".join(out)
    if max_len:
        result = result[:max_len]
    return result


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
            "  " + "-" * 30,
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
            "  " + "-" * 30,
            "  any key to close",
        ]

        self._setup_curses()

    def _setup_curses(self):
        curses.curs_set(0)          # hide cursor
        curses.noecho()
        self.stdscr.nodelay(True)   # non-blocking input
        self.stdscr.keypad(True)
        # Ask the OS to send KEY_RESIZE events so we detect terminal resize
        # (e.g. iPad keyboard appearing, device rotation).
        try:
            curses.use_env(True)
        except Exception:
            pass

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
        # update_lines_cols() is our last-resort resize catch inside the renderer;
        # the main loop's SIGWINCH flag is the primary defence.
        try:
            curses.update_lines_cols()
        except Exception:
            pass

        try:
            self.stdscr.erase()
            h, w = self.stdscr.getmaxyx()

            # Terminal too small to draw safely — just show a message and bail
            if h < 6 or w < 20:
                try:
                    self.stdscr.addstr(0, 0, "Terminal too small"[:w - 1])
                    self.stdscr.refresh()
                except curses.error:
                    pass
                return

            panel_w = min(42, max(1, w // 3))
            map_w   = max(1, w - panel_w - 1)
            map_h   = max(1, h - 1)

            self._draw_map(world_state, map_w, map_h)
            self._draw_divider(map_w, map_h)
            self._draw_panel(world_state, map_w + 1, panel_w, map_h)
            self._draw_bottom_bar(h - 1, w)

            if self.show_help:
                self._draw_help()

            self.stdscr.refresh()

        except curses.error:
            try:
                self.stdscr.clear()
                self.stdscr.refresh()
            except Exception:
                pass
        except Exception:
            pass   # swallow any other draw error — don't crash the game

    def _draw_map(self, world_state, map_w, map_h):
        world = world_state.world
        moriarty = world_state.moriarty

        # Snapshot the entity list once — prevents any mid-draw mutation
        # (including from the GC) from corrupting the iteration.
        entities = list(world_state.entities)

        # Pre-index entities by tile position so we don't scan all entities per tile
        player_at = {}    # (x,y) -> PlayerEntity
        creature_at = {}  # (x,y) -> first non-item, non-player entity (animals etc.)
        for e in entities:
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
            self._put(row, map_w, "|", curses.color_pair(PAIR_DIM))

    def _draw_panel(self, world_state, px, panel_w, map_h):
        """
        Draw the right-hand status panel.
        All text is wrapped to panel_w-2 chars and every write guards row < map_h.
        Header is kept compact so the log gets maximum vertical space.
        """
        moriarty = world_state.moriarty
        row = 0
        wrap_w = max(8, panel_w - 2)

        def put(text, attr=None):
            nonlocal row
            if row >= map_h:
                return False
            if attr is None:
                attr = curses.color_pair(PAIR_NORMAL)
            self._panel_text(row, px, panel_w, text, attr)
            row += 1
            return True

        def put_wrapped(text, attr=None, max_lines=2):
            """Write text wrapped to panel width. Returns False if panel full."""
            if attr is None:
                attr = curses.color_pair(PAIR_NORMAL)
            lines = textwrap.wrap(_safe(text), wrap_w) or [_safe(text)[:wrap_w]]
            for line in lines[:max_lines]:
                if not put(line, attr):
                    return False
            return True

        def divider():
            put("-" * (panel_w - 1), curses.color_pair(PAIR_DIM))

        # ── Compact header (mode + pos on same line to save rows) ─────────────
        label     = self.control_mode_label
        mode_attr = {
            "MORIARTY": curses.color_pair(PAIR_HIGHLIGHT),
            "GOD":      curses.color_pair(PAIR_WARNING) | curses.A_BOLD,
            "PLAYER":   curses.color_pair(PAIR_PLAYER)  | curses.A_BOLD,
        }.get(label, curses.color_pair(PAIR_WARNING) | curses.A_BOLD)

        if not put(f"MORIARTY [{label}]", mode_attr):
            return
        divider()

        put(f"({moriarty.x},{moriarty.y}) T:{world_state.tick}")
        warn = moriarty.status.hunger < 20 or moriarty.status.fatigue > 80
        put_wrapped(moriarty.status.describe(),
                    curses.color_pair(PAIR_WARNING) if warn
                    else curses.color_pair(PAIR_NORMAL),
                    max_lines=1)

        n, filled = 7, self.tick_delay_idx + 1
        bar = "#" * filled + "." * (n - filled)
        spd_attr = curses.color_pair(PAIR_WARNING) | curses.A_BOLD if self.stepped \
                   else curses.color_pair(PAIR_NORMAL)
        put(f"[{bar}] {'STEP' if self.stepped else str(self.tick_delay) + 's'}", spd_attr)

        divider()

        # ── Thought / reasoning ───────────────────────────────────────────────
        if self.reasoning_stream:
            if not put("~reasoning~", curses.color_pair(PAIR_DIM)):
                return
            tail = _safe(self.reasoning_stream[-150:])
            if len(tail) == 150:
                tail = tail[tail.find(" ") + 1:]
            for line in textwrap.wrap(tail, wrap_w)[-3:]:
                if not put(line, curses.color_pair(PAIR_DIM)):
                    return
        else:
            if not put("THOUGHT:", curses.color_pair(PAIR_DIM)):
                return
            if self.last_thought:
                thought_text = _safe(self.last_thought.strip())
                wrapped = textwrap.wrap(
                    thought_text, wrap_w,
                    break_long_words=True,
                    break_on_hyphens=True,
                )
                for line in wrapped[:3]:
                    if not put(line, curses.color_pair(PAIR_HIGHLIGHT)):
                        return

        divider()

        # ── Message log — wraps each message, fills remaining space ───────────
        if not put("LOG:", curses.color_pair(PAIR_DIM)):
            return

        # Work out how many rows we have left, then fill from most recent messages
        # Each message may take 1-2 wrapped lines; fill backwards from bottom.
        rows_left = map_h - row
        if rows_left <= 0:
            return

        # Pre-wrap all messages so we know how many rows each needs
        wrapped_msgs = []
        for msg in self.messages:
            lines = textwrap.wrap(_safe(msg), wrap_w) or [_safe(msg)[:wrap_w]]
            wrapped_msgs.append(lines[:2])   # cap at 2 lines per message

        # Pick the most recent messages that fit
        slots, chosen = rows_left, []
        for lines in reversed(wrapped_msgs):
            if slots >= len(lines):
                chosen.insert(0, lines)
                slots -= len(lines)
            if slots == 0:
                break

        total = len(chosen)
        for mi, lines in enumerate(chosen):
            age = total - mi
            attr = curses.color_pair(PAIR_DIM) if age > 4 \
                   else curses.color_pair(PAIR_NORMAL)
            for line in lines:
                if not put(line, attr):
                    return

    def _draw_bottom_bar(self, row, w):
        safe_w = max(1, w - 1)   # never write to the very last cell (curses error)
        if self.text_input_active:
            prompt = f" {self.text_input_prompt}: "
            text = _safe("".join(self.text_input_buffer))
            bar = _safe((prompt + text + "_")[:safe_w].ljust(safe_w))
            try:
                self.stdscr.addstr(row, 0, bar,
                                   curses.color_pair(PAIR_PLAYER) | curses.A_BOLD)
            except curses.error:
                pass
            return

        label = self.control_mode_label
        if label == "MORIARTY":
            bar = " TAB:drop-in  [:lag-  ]:lag+  SPC:step  .:advance  v:LOS  ?:help  q:quit "
        elif label == "DROP-IN?":
            bar = " G:god observer  P:player character  ESC:cancel "
        elif label == "GOD":
            bar = " TAB:return  arrows:pan  m:jump to Mo  t:inject  v:LOS  q:quit "
        elif label == "PLAYER":
            bar = " TAB:return  arrows:move  t:talk  p:pickup  e:examine  .:wait  q:quit "
        else:
            bar = " TAB:mode  q:quit "
        bar = bar[:safe_w].ljust(safe_w)
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
        """Draw floating speech text near speaking entities."""
        import time
        now = time.monotonic()
        expired = [n for n, b in self.speech_bubbles.items() if b["expires"] <= now]
        for n in expired:
            del self.speech_bubbles[n]

        if map_w < 4 or map_h < 3:
            return

        for name, bubble in self.speech_bubbles.items():
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

            sc = ex - self.view_x
            sr = ey - self.view_y

            # Prefer one row above; fall back to one row below; skip if both off-screen
            if 0 < sr < map_h:
                bubble_row = sr - 1
            elif sr == 0 and map_h > 1:
                bubble_row = 1
            else:
                continue

            # Sanitise BEFORE wrapping so length arithmetic is correct
            full_text = _safe(f'"{bubble["text"]}"')
            wrap_w = max(10, min(36, map_w - 4))  # narrower = easier to centre
            wrapped_lines = textwrap.wrap(full_text, wrap_w) or [full_text[:wrap_w]]

            for li, line in enumerate(wrapped_lines):
                row_y = bubble_row - li   # stack upward
                if row_y < 0:
                    row_y = bubble_row + li + 1   # flip below if no room above
                if row_y < 0 or row_y >= map_h:
                    continue

                # Centre on speaker, then shift left if needed to stay on screen
                start_col = sc - len(line) // 2
                if start_col + len(line) > map_w - 1:
                    start_col = max(0, map_w - 1 - len(line))
                if start_col < 0:
                    start_col = 0
                # Final clip (text wider than entire map)
                line = line[:max(0, map_w - start_col)]
                if line:
                    self._put(row_y, start_col, line,
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
        """Safe character put — sanitises to ASCII and ignores out-of-bounds."""
        try:
            self.stdscr.addstr(row, col, _safe(char), attr)
        except curses.error:
            pass

    def _panel_text(self, row, px, panel_w, text, attr=None):
        """Write sanitised text in the panel, truncated to panel width."""
        if attr is None:
            attr = curses.color_pair(PAIR_NORMAL)
        text = _safe(text, max_len=panel_w - 1)
        try:
            self.stdscr.addstr(row, px, text, attr)
        except curses.error:
            pass
