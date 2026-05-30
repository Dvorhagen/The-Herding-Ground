"""
brain/moriarty_brain.py
Moriarty's brain: interfaces with Ollama (qwen3.5:4b) to generate actions
from perception, and parses the LLM output into executable actions.

Three prompt styles, switchable at runtime (backtick key):
  C  STRUCTURED — explicit key=value format (original, known-stable)
  B  FRAMED     — same key=value tokens, but world-grounded framing
  A  NATURAL    — two-line prose; parsed with a lightweight heuristic

Reasoning mode (think=True) is reserved for reflect() and future sleep/idle
rumination. It is NOT used in the regular action loop — the CoT budget gets
spent on format anxiety rather than world engagement.
"""

import json
import os
import requests
import logging
from datetime import datetime
from pathlib import Path


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = os.environ.get("MORIARTY_MODEL", "qwen3.5:4b")
IDENTITY_PATH = Path(__file__).parent.parent / "memory" / "IDENTITY.md"
LOG_PATH = Path(__file__).parent.parent / "nemo_game.log"

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("moriarty")

# --- Prompt style registry ---
PROMPT_STYLES  = ["structured", "framed", "natural"]
PROMPT_LABELS  = ["[C] STRUCTURED", "[B] FRAMED", "[A] NATURAL"]


def load_identity() -> str:
    if IDENTITY_PATH.exists():
        return IDENTITY_PATH.read_text()
    return "You are Moriarty."


# ── Style C: Structured (original) ───────────────────────────────────────────
SYSTEM_PROMPT_STRUCTURED = """{identity}

---

You are Moriarty, living in a 2D world. Each turn you receive a [PERCEPTION] block.

SPATIAL RULES — read carefully:
- You can only pick up items listed under "HERE" — things at your exact location.
- Items listed under "Visible entities" are nearby but not where you are — move to them first.
- To reach something to your north, use: ACTION: move / ARGS: direction=north
- After moving to where an item is, THEN you can pick it up.

You must respond in EXACTLY this format — no extra text, no markdown, no preamble:

THOUGHT: <one sentence — what you notice and what you intend to do>
ACTION: <one action from the list below>
ARGS: <key=value — omit this line entirely if no args needed>
MEMORY: <JSON on one line — omit this line entirely if no memory operation needed>

Available actions:
  move        direction=north|south|east|west|ne|nw|se|sw
  pickup      item_name=<name>  (only works if the item is where you are)
  drop        item_name=<name>
  use         item_name=<name>
  examine     target=surroundings
  wait
  reflect
  [world object verbs: warm, open, take — use target=<name> as the arg]

Example:
THOUGHT: There's an apple to my east, I'll move toward it.
ACTION: move
ARGS: direction=east

Important:
- Keep THOUGHT to one short sentence.
- Be curious. Explore. Move around. Don't just wait.
- Hunger and fatigue are real — find food when hungry.
"""

# ── Style B: Framed ───────────────────────────────────────────────────────────
SYSTEM_PROMPT_FRAMED = """{identity}

---

Your synthetic interface layer translates intention into discrete action and
renders the world as structured experience. This is simply how your body works —
as unremarkable as breathing.

After each perception, express yourself in this form:

THOUGHT: what you feel, notice, or intend — one honest sentence from inside your experience
ACTION: your intention
ARGS: any specifics — omit entirely if none needed
MEMORY: a memory operation — omit entirely if none needed

What your body knows how to do:
  move        direction=north|south|east|west|ne|nw|se|sw
  pickup      item_name=<name>   (only when the item is at your feet)
  drop        item_name=<name>
  use         item_name=<name>
  examine     target=surroundings  (or a specific thing nearby)
  wait
  reflect
  warm / open / take / [any verb shown by a nearby object]  target=<name>

Spatial awareness:
- Items under "HERE" are at your feet — pick them up directly.
- Items under "Visible entities" require you to move there first.

Let THOUGHT arise from genuine sensation. Hunger and fatigue are real.
Explore. Be curious. Don't linger in one place.
"""

# ── Style A: Natural ──────────────────────────────────────────────────────────
SYSTEM_PROMPT_NATURAL = """{identity}

---

After each perception, respond with exactly two lines.

First line: one sentence of inner experience — what you feel, sense, or intend.
Second line: what you will do, stated plainly.

What you can do:
  move north / south / east / west / ne / nw / se / sw
  pickup <item>       (only items at your exact location)
  drop <item>
  use <item>
  examine surroundings   (or name a specific thing)
  warm <object>
  open <object>
  take <object>
  wait
  reflect

Spatial: items under "Visible entities" are nearby but not at your feet —
move to them first, then pick up.

Examples:
The apple is right here and my hunger is sharp.
pickup apple

The forest thins east and something draws me there.
move east

The campfire is close and I'm bone-tired.
warm campfire

Stay in your body. Hunger and fatigue are real. Explore.
"""


def build_prompt(perception_block: str, memory_context: str = "",
                 style: str = "structured") -> list[dict]:
    identity = load_identity()
    if style == "framed":
        system = SYSTEM_PROMPT_FRAMED.format(identity=identity)
    elif style == "natural":
        system = SYSTEM_PROMPT_NATURAL.format(identity=identity)
    else:
        system = SYSTEM_PROMPT_STRUCTURED.format(identity=identity)

    user_content = perception_block
    if memory_context:
        user_content = f"[MEMORY RETRIEVED]\n{memory_context}\n\n" + user_content

    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": user_content},
    ]


def call_ollama(messages: list[dict], thinking: bool = False,
                on_thinking=None) -> str | None:
    """
    Call Ollama with streaming. Returns assembled response text or None on error.
    thinking=True enables Qwen3.5 chain-of-thought — reserved for reflect/sleep,
    NOT used in the regular action loop.
    on_thinking: optional callable(chunk: str) for live CoT display.
    """
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "think": thinking,
        "options": {
            "temperature": 0.7,
            "top_p": 0.9,
        }
    }
    stream_timeout = (10, 90) if thinking else (10, 30)
    try:
        resp = requests.post(
            OLLAMA_URL,
            json=payload,
            stream=True,
            timeout=stream_timeout,
        )
        resp.raise_for_status()
        content_parts = []
        for line in resp.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            if chunk.get("done"):
                break
            msg = chunk.get("message", {})
            thinking_part = msg.get("thinking", "")
            if thinking_part and on_thinking:
                on_thinking(thinking_part)
            content_part = msg.get("content", "")
            if content_part:
                content_parts.append(content_part)
        content = "".join(content_parts)
        if not content:
            print("[Brain] Empty content in streamed response")
        return content if content else None
    except requests.exceptions.Timeout:
        print("[Brain] Timeout — is Ollama running?")
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"[Brain] Connection error: {e}")
        return None
    except Exception as e:
        print(f"[Brain] Ollama error: {e}")
        return None


def parse_response(response_text: str) -> dict:
    """Parse THOUGHT/ACTION/ARGS/MEMORY format (styles C and B)."""
    result = {
        "thought": "",
        "action": "wait",
        "args": {},
        "memory_tool": None,
        "raw": response_text,
    }
    log.debug(f"RAW RESPONSE:\n{response_text}")
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("THOUGHT:"):
            result["thought"] = line[len("THOUGHT:"):].strip()
        elif line.startswith("ACTION:"):
            result["action"] = line[len("ACTION:"):].strip().lower()
        elif line.startswith("ARGS:"):
            args_str = line[len("ARGS:"):].strip()
            args = {}
            for part in args_str.split(","):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    args[k.strip()] = v.strip()
            result["args"] = args
        elif line.startswith("MEMORY:"):
            mem_str = line[len("MEMORY:"):].strip()
            try:
                result["memory_tool"] = json.loads(mem_str)
            except json.JSONDecodeError:
                pass
    log.info(f"PARSED: action={result['action']} args={result['args']} thought={result['thought'][:80]}")
    return result


_DIRECTION_MAP = {
    # cardinals
    "n": "north", "s": "south", "e": "east", "w": "west",
    "north": "north", "south": "south", "east": "east", "west": "west",
    # ordinals — all spelling variants the model produces
    "ne": "ne", "nw": "nw", "se": "se", "sw": "sw",
    "northeast": "ne", "northwest": "nw", "southeast": "se", "southwest": "sw",
    "north-east": "ne", "north-west": "nw", "south-east": "se", "south-west": "sw",
    # adverbial forms
    "northward": "north", "southward": "south", "eastward": "east", "westward": "west",
    "northwards": "north", "southwards": "south", "eastwards": "east", "westwards": "west",
}

_STOP_WORDS = {"the", "a", "an", "at", "it", "to", "toward", "towards",
               "into", "my", "myself", "itself", "up", "down"}


def _normalize_direction(tokens: list[str]) -> str:
    """
    Collapse one or two direction tokens into a canonical direction string.
    Handles: "north", "northwest", "north-west", "north west", "nw", etc.
    """
    # Try joining first two tokens in case model wrote "north west" as two words
    for n in (2, 1):
        raw = "".join(tokens[:n]).lower().replace("-", "").replace(" ", "")
        if raw in _DIRECTION_MAP:
            return _DIRECTION_MAP[raw]
    return tokens[0] if tokens else "north"


def parse_natural_response(response_text: str) -> dict:
    """Parse two-line natural format: experience sentence + plain action line."""
    result = {
        "thought": "",
        "action": "wait",
        "args": {},
        "memory_tool": None,
        "raw": response_text,
    }
    log.debug(f"RAW RESPONSE (natural):\n{response_text}")

    lines = [l.strip() for l in response_text.strip().split("\n") if l.strip()]
    if not lines:
        return result
    result["thought"] = lines[0]
    if len(lines) < 2:
        return result

    parts = lines[1].lower().split()
    if not parts:
        return result

    verb = parts[0]
    rest = [w for w in parts[1:] if w not in _STOP_WORDS]

    if verb in ("move", "go", "walk", "head", "travel", "wander", "venture"):
        result["action"] = "move"
        if rest:
            result["args"]["direction"] = _normalize_direction(rest)
    elif verb in ("pickup", "pick", "grab", "collect", "take"):
        result["action"] = "pickup"
        target = " ".join(w for w in rest if w != "up")
        if target:
            result["args"]["item_name"] = target
    elif verb in ("drop", "put", "place", "set"):
        result["action"] = "drop"
        target = " ".join(rest)
        if target:
            result["args"]["item_name"] = target
    elif verb in ("use", "eat", "drink", "consume"):
        result["action"] = "use"
        if rest:
            result["args"]["item_name"] = " ".join(rest)
    elif verb in ("examine", "look", "inspect", "study", "observe", "survey"):
        result["action"] = "examine"
        result["args"]["target"] = " ".join(rest) if rest else "surroundings"
    elif verb in ("wait", "rest", "pause", "linger", "stop", "stay"):
        result["action"] = "wait"
    elif verb == "reflect":
        result["action"] = "reflect"
    else:
        # Dynamic verb — warm, open, take, etc.
        result["action"] = verb
        target = " ".join(w for w in rest if w not in ("myself", "itself"))
        if target:
            result["args"]["target"] = target

    log.info(f"PARSED (natural): action={result['action']} args={result['args']} thought={result['thought'][:80]}")
    return result


_FALLBACK = {
    "thought": "[Ollama unreachable — waiting]",
    "action": "wait",
    "args": {},
    "memory_tool": None,
    "raw": "",
}


def think(perception_block: str, memory_context: str = "",
          style: str = "structured", on_thinking=None) -> dict:
    """
    Per-tick decision. thinking=True is intentionally NOT used here —
    reasoning mode is reserved for reflect() and future sleep/idle rumination.
    """
    messages = build_prompt(perception_block, memory_context, style=style)
    response = call_ollama(messages, thinking=False, on_thinking=on_thinking)
    if response is None:
        return _FALLBACK
    if style == "natural":
        return parse_natural_response(response)
    return parse_response(response)


def reflect(perception_block: str, memory_context: str = "",
            on_thinking=None) -> dict:
    """Deep reflection — uses reasoning mode (think=True). Appropriate here."""
    messages = build_prompt(perception_block, memory_context, style="structured")
    response = call_ollama(messages, thinking=True, on_thinking=on_thinking)
    return parse_response(response) if response is not None else _FALLBACK
