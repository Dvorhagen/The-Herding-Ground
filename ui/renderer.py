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
COLOR_NEMO       = (120, 255, 120)
COLOR_PLAYER     = (255, 255, 100)

FONT_PATH = None   # Use pygame default monospace


class Renderer:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("NEMO // World Engine v0.1")

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

        # Nemo's last thought
        self.last_thought = ""

        self.tick_delay_idx = 3   # set by main.py
        self.tick_delay = 1.0
        self.stepped = False
        self.show_los = False
        self.show_help = False

        self._fog = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        self._fog.fill((0, 0, 0, 180))

        self._help_lines = [
            "  KEY REFERENCE",
            "  ─────────────────────────",
            "  TAB        Aaron / Nemo mode",
            "  arrows     move (Aaron mode)",
            "  [ / ]      tick speed",
            "  SPACE      step mode on/off",
            "  .          advance one step",
            "  v          LOS overlay",
            "  r          reasoning mode",
            "  ?          this help",
            "  q          quit",
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

    def draw(self, world_state):
        self.screen.fill(COLOR_BG)
        self._draw_map(world_state)
        self._draw_entities(world_state)
        self._draw_panel(world_state)
        self.screen.blit(self._scanlines, (0, 0))
        if self.show_help:
            self._draw_help()
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
        # Items
        for entity in world_state.entities:
            sx, sy = self.world_to_screen(entity.x, entity.y)
            if 0 <= sx < VIEWPORT_W * TILE_SIZE and 0 <= sy < VIEWPORT_H * TILE_SIZE:
                sym = self.font_md.render(entity.symbol, True, entity.color)
                self.screen.blit(sym, (sx + 2, sy + 1))

        # Nemo
        nemo = world_state.nemo
        sx, sy = self.world_to_screen(nemo.x, nemo.y)
        if 0 <= sx < VIEWPORT_W * TILE_SIZE and 0 <= sy < VIEWPORT_H * TILE_SIZE:
            # Glow effect: slightly larger rect behind N
            pygame.draw.rect(self.screen, (30, 80, 30), (sx, sy, TILE_SIZE, TILE_SIZE))
            sym = self.font_md.render("@", True, COLOR_NEMO)
            self.screen.blit(sym, (sx + 2, sy + 1))

    def _draw_panel(self, world_state):
        px = VIEWPORT_W * TILE_SIZE
        # Panel background
        pygame.draw.rect(self.screen, COLOR_PANEL_BG, (px, 0, PANEL_W, SCREEN_H))
        pygame.draw.line(self.screen, COLOR_BORDER, (px, 0), (px, SCREEN_H), 2)

        y = 8
        # Title
        title = self.font_lg.render("// NEMO", True, COLOR_HIGHLIGHT)
        self.screen.blit(title, (px + 10, y))
        y += 28

        # Divider
        pygame.draw.line(self.screen, COLOR_BORDER, (px + 8, y), (px + PANEL_W - 8, y), 1)
        y += 8

        # Status
        nemo = world_state.nemo
        self._text(f"POS  : ({nemo.x}, {nemo.y})", px + 10, y)
        y += 18
        self._text(f"TICK : {world_state.tick}", px + 10, y)
        y += 18
        self._text(f"STATE: {nemo.status.describe()}", px + 10, y, max_width=PANEL_W - 20)
        y += 18

        # Inventory
        inv = nemo.describe_inventory()
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

        # Thought
        thought_label = self.font_sm.render("THOUGHT:", True, COLOR_TEXT_DIM)
        self.screen.blit(thought_label, (px + 10, y))
        y += 16
        if self.last_thought:
            y = self._wrapped_text(self.last_thought, px + 10, y, PANEL_W - 20, COLOR_HIGHLIGHT)
        y += 8

        # Divider
        pygame.draw.line(self.screen, COLOR_BORDER, (px + 8, y), (px + PANEL_W - 8, y), 1)
        y += 8

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
