"""
ui/renderer.py
Pygame renderer. Green phosphor CRT aesthetic.
Tile-based map on the left, info panel on the right.
"""

import pygame
from ..world.tiles import TILE_PROPERTIES, TileType, PHOSPHOR_BG, PHOSPHOR_BRIGHT, PHOSPHOR_GLOW, PHOSPHOR_WHITE, PHOSPHOR_MID, PHOSPHOR_DIM


# Layout constants
TILE_SIZE    = 16           # pixels per tile
VIEWPORT_W   = 40           # tiles wide in viewport
VIEWPORT_H   = 30           # tiles tall in viewport
PANEL_W      = 360          # right info panel width in pixels
SCREEN_W     = VIEWPORT_W * TILE_SIZE + PANEL_W
SCREEN_H     = VIEWPORT_H * TILE_SIZE

# Phosphor palette
COLOR_BG         = PHOSPHOR_BG
COLOR_PANEL_BG   = (8, 14, 8)
COLOR_BORDER     = PHOSPHOR_MID
COLOR_TEXT       = PHOSPHOR_BRIGHT
COLOR_TEXT_DIM   = PHOSPHOR_DIM
COLOR_HIGHLIGHT  = PHOSPHOR_GLOW
COLOR_MORIARTY       = (120, 255, 120)
COLOR_PLAYER     = (255, 255, 100)

FONT_PATH = None   # Use pygame default monospace


class Renderer:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("MORIARTY // World Engine")

        # Fonts -- monospace for that terminal feel
        self.font_sm = pygame.font.SysFont("monospace", 13)
        self.font_md = pygame.font.SysFont("monospace", 15)
        self.font_lg = pygame.font.SysFont("monospace", 18, bold=True)

        # Viewport offset (top-left tile coords)
        self.view_x = 0
        self.view_y = 0

        # Log buffer for the message panel (last N messages)
        self.messages: list[str] = []
        self.max_messages = 20

        # Moriarty's last thought and live reasoning stream
        self.last_thought = ""
        self.reasoning_stream = ""   # live CoT tokens; set by main.py callback

        self.tick_delay_idx = 3   # set by main.py
        self.tick_delay = 1.0
        self.stepped = False
        self.show_los = False
        self.show_help = False
        self.control_mode_label = "MORIARTY"
        self.player_entity = None       # set by main.py when avatar is active

        # Non-blocking text input (same pattern as curses renderer)
        self.text_input_active = False
        self.text_input_prompt = ""
        self.text_input_buffer = []
        self.text_input_mode = ""   # "god_inject" | "player_talk"

        # Speech bubbles: actor_name.lower() -> {text, expires}
        self.speech_bubbles = {}

        self._fog = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        self._fog.fill((0, 0, 0, 180))

        self._help_lines = [
            "  KEY REFERENCE",
            "  ─────────────────────────",
            "  TAB        drop in / return to Mo",
            "  [MORIARTY MODE]",
            "  [ / ]      Mo lag between decisions",
            "  SPACE      step mode  .  advance",
            "  `          cycle prompt style",
            "  [GOD MODE]",
            "  arrows     pan camera   m: jump to Mo",
            "  t          inject [ENVIRONMENT]",
            "  [PLAYER MODE]",
            "  arrows     move avatar",
            "  t          talk to Moriarty",
            "  p          pick up item",
            "  [ALWAYS]",
            "  v          LOS overlay",
            "  ?          this help   q  quit",
            "  ─────────────────────────",
            "  any key to close",
        ]

        # Scanline surface for CRT effect
        self._scanlines = self._make_scanlines()

    def _make_scanlines(self) -> pygame.Surface:
        """Creates a semi-transparent scanline overlay for CRT feel."""
        surf = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        for y in range(0, SCREEN_H, 2):
            pygame.draw.line(surf, (0, 0, 0, 40), (0, y), (SCREEN_W, y))
        return surf

    def add_message(self, msg: str):
        """Add a line to the message log."""
        # Word-wrap to panel width
        max_chars = (PANEL_W - 20) // 8
        while len(msg) > max_chars:
            self.messages.append(msg[:max_chars])
            msg = "  " + msg[max_chars:]
        self.messages.append(msg)
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def center_on(self, x: int, y: int):
        """Center the viewport on a world position."""
        self.view_x = max(0, x - VIEWPORT_W // 2)
        self.view_y = max(0, y - VIEWPORT_H // 2)

    def world_to_screen(self, wx: int, wy: int) -> tuple[int, int]:
        return ((wx - self.view_x) * TILE_SIZE, (wy - self.view_y) * TILE_SIZE)

    def add_speech_bubble(self, actor_name: str, text: str, duration: float = 7.0):
        import time
        if len(text) > 200:
            text = text[:197] + "..."
        self.speech_bubbles[actor_name.lower()] = {
            "text": text,
            "expires": time.monotonic() + duration,
        }

    def draw(self, world_state):
        self.screen.fill(COLOR_BG)
        self._draw_map(world_state)
        self._draw_entities(world_state)
        self._draw_speech_bubbles(world_state)
        self._draw_panel(world_state)
        self.screen.blit(self._scanlines, (0, 0))
        if self.show_help:
            self._draw_help()
        if self.text_input_active:
            self._draw_text_input_bar()
        pygame.display.flip()

    def _draw_help(self):
        lh = 18
        pad = 16
        box_w = 320
        box_h = len(self._help_lines) * lh + pad * 2
        bx = (SCREEN_W - box_w) // 2
        by = (SCREEN_H - box_h) // 2
        overlay = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        overlay.fill((10, 20, 10, 230))
        self.screen.blit(overlay, (bx, by))
        pygame.draw.rect(self.screen, COLOR_BORDER, (bx, by, box_w, box_h), 1)
        for i, line in enumerate(self._help_lines):
            color = COLOR_HIGHLIGHT if i == 0 else COLOR_TEXT
            surf = self.font_sm.render(line, True, color)
            self.screen.blit(surf, (bx + pad, by + pad + i * lh))

    def _draw_map(self, world_state):
        world = world_state.world
        for ty in range(VIEWPORT_H):
            for tx in range(VIEWPORT_W):
                wx, wy = tx + self.view_x, ty + self.view_y
                tile = world.get(wx, wy)
                if tile is None:
                    continue
                color = tile.props.color
                sx, sy = tx * TILE_SIZE, ty * TILE_SIZE
                pygame.draw.rect(self.screen, color, (sx, sy, TILE_SIZE, TILE_SIZE))
                sym = self.font_sm.render(tile.props.symbol, True, self._darken(color, 0.5))
                self.screen.blit(sym, (sx + 3, sy + 2))
                if self.show_los and (wx, wy) not in world_state.visible_tiles:
                    self.screen.blit(self._fog, (sx, sy))

    def _draw_entities(self, world_state):
        # World objects (drawn first so entities/Moriarty appear on top)
        for obj in world_state.world_objects:
            sx, sy = self.world_to_screen(obj.x, obj.y)
            if 0 <= sx < VIEWPORT_W * TILE_SIZE and 0 <= sy < VIEWPORT_H * TILE_SIZE:
                sym = self.font_md.render(obj.symbol, True, obj.color)
                self.screen.blit(sym, (sx + 2, sy + 1))

        # Items / entities
        for entity in world_state.entities:
            sx, sy = self.world_to_screen(entity.x, entity.y)
            if 0 <= sx < VIEWPORT_W * TILE_SIZE and 0 <= sy < VIEWPORT_H * TILE_SIZE:
                sym = self.font_md.render(entity.symbol, True, entity.color)
                self.screen.blit(sym, (sx + 2, sy + 1))

        # Moriarty
        moriarty = world_state.moriarty
        sx, sy = self.world_to_screen(moriarty.x, moriarty.y)
        if 0 <= sx < VIEWPORT_W * TILE_SIZE and 0 <= sy < VIEWPORT_H * TILE_SIZE:
            # Glow effect: slightly larger rect behind N
            pygame.draw.rect(self.screen, (30, 80, 30), (sx, sy, TILE_SIZE, TILE_SIZE))
            sym = self.font_md.render("@", True, COLOR_MORIARTY)
            self.screen.blit(sym, (sx + 2, sy + 1))

    def _draw_speech_bubbles(self, world_state):
        import time
        now = time.monotonic()
        expired = [n for n, b in self.speech_bubbles.items() if b["expires"] <= now]
        for n in expired:
            del self.speech_bubbles[n]

        MAX_LINE_PX = 260   # max bubble width in pixels
        CHARS_PER_LINE = MAX_LINE_PX // 8   # approximate; font_sm ~8px wide

        for name, bubble in self.speech_bubbles.items():
            mo = world_state.moriarty
            if name in (mo.name.lower(), "moriarty"):
                ex, ey = mo.x, mo.y
            else:
                found = next(
                    (e for e in world_state.entities if e.name.lower() == name), None
                )
                if not found:
                    continue
                ex, ey = found.x, found.y

            sx, sy = self.world_to_screen(ex, ey)
            if not (0 <= sx < VIEWPORT_W * TILE_SIZE):
                continue

            # Word-wrap the text
            raw = f'"{bubble["text"]}"'
            words = raw.split()
            lines = []
            current = ""
            for word in words:
                if len(current) + len(word) + 1 <= CHARS_PER_LINE:
                    current = current + (" " if current else "") + word
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
            if not lines:
                continue

            line_h = self.font_sm.get_height() + 2
            bw = min(MAX_LINE_PX, max(self.font_sm.size(l)[0] for l in lines)) + 12
            bh = len(lines) * line_h + 8

            bx = sx - bw // 2 + TILE_SIZE // 2
            bx = max(0, min(VIEWPORT_W * TILE_SIZE - bw, bx))
            bubble_y = sy - bh - 4
            if bubble_y < 0:
                bubble_y = sy + TILE_SIZE + 2

            bubble_surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
            bubble_surf.fill((10, 25, 10, 230))
            pygame.draw.rect(bubble_surf, (200, 255, 200), (0, 0, bw, bh), 1)
            for i, line in enumerate(lines):
                line_surf = self.font_sm.render(line, True, (255, 255, 255))
                bubble_surf.blit(line_surf, (6, 4 + i * line_h))
            self.screen.blit(bubble_surf, (bx, bubble_y))

    def _draw_text_input_bar(self):
        prompt = f" {self.text_input_prompt}: "
        text = "".join(self.text_input_buffer)
        display = prompt + text + "_"
        bar_h = 30
        bar_y = SCREEN_H - bar_h
        pygame.draw.rect(self.screen, (60, 50, 0), (0, bar_y, SCREEN_W, bar_h))
        pygame.draw.rect(self.screen, COLOR_PLAYER, (0, bar_y, SCREEN_W, 2))
        surf = self.font_md.render(display, True, COLOR_PLAYER)
        self.screen.blit(surf, (8, bar_y + 7))

    def _draw_panel(self, world_state):
        px = VIEWPORT_W * TILE_SIZE
        pygame.draw.rect(self.screen, COLOR_PANEL_BG, (px, 0, PANEL_W, SCREEN_H))
        pygame.draw.line(self.screen, COLOR_BORDER, (px, 0), (px, SCREEN_H), 2)

        y = 8
        # Title + control mode
        title = self.font_lg.render("// MORIARTY", True, COLOR_HIGHLIGHT)
        self.screen.blit(title, (px + 10, y))
        mode_color = (COLOR_PLAYER if self.control_mode_label in ("PLAYER", "GOD", "DROP-IN?")
                      else COLOR_TEXT_DIM)
        mode_surf = self.font_sm.render(self.control_mode_label, True, mode_color)
        self.screen.blit(mode_surf, (px + PANEL_W - mode_surf.get_width() - 10, y + 4))
        y += 28

        # Divider
        pygame.draw.line(self.screen, COLOR_BORDER, (px + 8, y), (px + PANEL_W - 8, y), 1)
        y += 8

        # Status
        moriarty = world_state.moriarty
        self._text(f"POS  : ({moriarty.x}, {moriarty.y})", px + 10, y)
        y += 18
        self._text(f"TICK : {world_state.tick}", px + 10, y)
        y += 18
        self._text(f"STATE: {moriarty.status.describe()}", px + 10, y, max_width=PANEL_W - 20)
        y += 18

        # Inventory
        inv = moriarty.describe_inventory()
        self._text(f"CARRY: {inv}", px + 10, y, max_width=PANEL_W - 20)
        y += 20

        # Speed bar
        n = 7
        seg_w, seg_h, seg_gap = 18, 8, 2
        bar_x = px + 10
        for i in range(n):
            color = COLOR_HIGHLIGHT if i <= self.tick_delay_idx else COLOR_TEXT_DIM
            pygame.draw.rect(self.screen, color,
                             (bar_x + i * (seg_w + seg_gap), y, seg_w, seg_h))
        label = "STEP" if self.stepped else f"{self.tick_delay}s"
        spd_color = (255, 100, 60) if self.stepped else COLOR_TEXT
        self._text(label, bar_x + n * (seg_w + seg_gap) + 6, y - 1, color=spd_color)
        y += 18

        # Divider
        pygame.draw.line(self.screen, COLOR_BORDER, (px + 8, y), (px + PANEL_W - 8, y), 1)
        y += 8

        # Thought / live reasoning stream
        if self.reasoning_stream:
            label = self.font_sm.render("REASONING:", True, (80, 160, 80))
            self.screen.blit(label, (px + 10, y))
            y += 16
            # Show the tail of the stream — last ~300 chars, trimmed to a word boundary
            tail = self.reasoning_stream[-300:]
            if len(self.reasoning_stream) > 300:
                tail = "…" + tail[tail.find(" ") + 1:]
            y = self._wrapped_text(tail, px + 10, y, PANEL_W - 20, (60, 130, 60))
        else:
            thought_label = self.font_sm.render("THOUGHT:", True, COLOR_TEXT_DIM)
            self.screen.blit(thought_label, (px + 10, y))
            y += 16
            if self.last_thought:
                y = self._wrapped_text(self.last_thought, px + 10, y, PANEL_W - 20, COLOR_HIGHLIGHT)
        y += 8

        # Divider
        pygame.draw.line(self.screen, COLOR_BORDER, (px + 8, y), (px + PANEL_W - 8, y), 1)
        y += 8

        # Player inventory / equipment panel (when avatar is active)
        pe = self.player_entity
        if pe and not getattr(pe, 'is_god', False):
            pygame.draw.line(self.screen, COLOR_BORDER, (px + 8, y), (px + PANEL_W - 8, y), 1)
            y += 6
            plabel = self.font_sm.render(f"YOU ({pe.name})", True, COLOR_PLAYER)
            self.screen.blit(plabel, (px + 10, y)); y += 15
            # Carrying
            inv_str = pe.describe_inventory()[:40]
            self._text(f"Carry: {inv_str}", px + 10, y, max_width=PANEL_W - 20); y += 14
            # Wearing
            wearing_lines = pe.describe_wearing().split("\n")
            for wl in wearing_lines[:3]:
                self._text(wl[:40], px + 10, y, color=COLOR_TEXT_DIM, max_width=PANEL_W - 20)
                y += 13
            # Hotkeys reminder
            self._text("P:pick D:drop U:use E:exam F:atk G:grap W:equip /:cmd",
                       px + 10, y, color=COLOR_TEXT_DIM, max_width=PANEL_W - 20)
            y += 15

        # Message log
        log_label = self.font_sm.render("LOG:", True, COLOR_TEXT_DIM)
        self.screen.blit(log_label, (px + 10, y))
        y += 16

        available_height = SCREEN_H - y - 8
        line_height = 15
        max_lines = available_height // line_height
        visible_messages = self.messages[-max_lines:]
        for i, msg in enumerate(visible_messages):
            alpha = 180 + int(75 * i / max(1, len(visible_messages) - 1))
            color = tuple(min(255, int(c * alpha / 255)) for c in COLOR_TEXT)
            surf = self.font_sm.render(msg, True, color)
            self.screen.blit(surf, (px + 10, y))
            y += line_height

    def _text(self, text: str, x: int, y: int, color=None, max_width: int = None):
        color = color or COLOR_TEXT
        if max_width:
            max_chars = max_width // 8
            if len(text) > max_chars:
                text = text[:max_chars - 1] + "…"
        surf = self.font_sm.render(text, True, color)
        self.screen.blit(surf, (x, y))

    def _wrapped_text(self, text: str, x: int, y: int, max_width: int, color=None) -> int:
        """Draw word-wrapped text. Returns new y position."""
        color = color or COLOR_TEXT
        max_chars = max_width // 8
        words = text.split()
        line = ""
        for word in words:
            if len(line) + len(word) + 1 <= max_chars:
                line += (" " if line else "") + word
            else:
                surf = self.font_sm.render(line, True, color)
                self.screen.blit(surf, (x, y))
                y += 15
                line = word
        if line:
            surf = self.font_sm.render(line, True, color)
            self.screen.blit(surf, (x, y))
            y += 15
        return y

    @staticmethod
    def _darken(color: tuple, factor: float) -> tuple:
        return tuple(int(c * factor) for c in color)
