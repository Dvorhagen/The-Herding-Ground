"""
brain/nemo_brain.py
Nemo's brain: interfaces with Ollama (qwen3.5:4b) to generate actions
from perception, and parses the LLM output into executable actions.

The brain does three things each tick:
1. Builds a prompt from the current world perception + identity + recent memory
2. Calls Ollama
3. Parses the response into an action dict

Output format we ask Nemo to produce:
  THOUGHT: <Nemo's internal monologue -- not executed, logged for flavor>
  ACTION: <action_name>
  ARGS: <key=value pairs, optional>
  MEMORY: <optional memory tool call in JSON>
"""

import json
import os
import requests
import logging
from datetime import datetime
from pathlib import Path


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = os.environ.get("NEMO_MODEL", "qwen3.5:4b")
IDENTITY_PATH = Path(__file__).parent.parent / "memory" / "IDENTITY.md"
LOG_PATH = Path(__file__).parent.parent / "nemo_game.log"

# Set up file logger
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("nemo")


def load_identity() -> str:
    if IDENTITY_PATH.exists():
        return IDENTITY_PATH.read_text()
    return "You are Nemo."


SYSTEM_PROMPT_TEMPLATE = """{identity}

---

You are Nemo, living in a 2D world. Each turn you receive a [PERCEPTION] block.

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

Example of correct response:
THOUGHT: There's an apple to my east, I'll move toward it.
ACTION: move
ARGS: direction=east

Example of correct response when an item is at your location:
THOUGHT: The apple is right here, I'll pick it up.
ACTION: pickup
ARGS: item_name=apple

Important:
- Keep THOUGHT to one short sentence. Save philosophy for the reflect action.
- Be curious. Explore. Move around. Don't just wait.
- Hunger and fatigue are real — find food when hungry.
- Respond with THOUGHT/ACTION/ARGS only. Nothing else.
"""


def build_prompt(perception_block: str, memory_context: str = "") -> list[dict]:
    """
    Builds the messages array for the Ollama API call.
    """
    identity = load_identity()
    system = SYSTEM_PROMPT_TEMPLATE.format(identity=identity)

    user_content = perception_block
    if memory_context:
        user_content = f"[MEMORY RETRIEVED]\n{memory_context}\n\n" + user_content

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


def call_ollama(messages: list[dict], thinking: bool = False, timeout: int = 20) -> str | None:
    """
    Call Ollama with the given messages. Returns the response text or None on error.
    thinking=True enables Qwen3.5's reasoning mode (slower, used for reflect()).
    """
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": thinking,
        "options": {
            "temperature": 0.7,
            "top_p": 0.9,
        }
    }
    try:
        resp = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        # Qwen3.5 returns thinking separately in message.thinking; we want message.content
        content = data.get("message", {}).get("content", "")
        if not content:
            print(f"[Brain] Empty content in response. Full response keys: {list(data.keys())}")
        return content if content else None
    except requests.exceptions.Timeout:
        print(f"[Brain] Timeout after {timeout}s — model may be overloaded")
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"[Brain] Connection error: {e}")
        return None
    except Exception as e:
        print(f"[Brain] Ollama error: {e}")
        return None


def parse_response(response_text: str) -> dict:
    result = {
        "thought": "",
        "action": "wait",
        "args": {},
        "memory_tool": None,
        "raw": response_text,
    }

    log.debug(f"RAW RESPONSE:\n{response_text}")

    lines = response_text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("THOUGHT:"):
            result["thought"] = line[len("THOUGHT:"):].strip()
        elif line.startswith("ACTION:"):
            result["action"] = line[len("ACTION:"):].strip().lower()
        elif line.startswith("ARGS:"):
            args_str = line[len("ARGS:"):].strip()
            # Parse key=value pairs
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
                pass  # Malformed memory call -- ignore

    log.info(f"PARSED: action={result['action']} args={result['args']} thought={result['thought'][:80]}")
    return result


_FALLBACK = {
    "thought": "[Ollama unreachable — waiting]",
    "action": "wait",
    "args": {},
    "memory_tool": None,
    "raw": "",
}


def think(perception_block: str, memory_context: str = "", reasoning: bool = False) -> dict:
    """Per-tick decision. reasoning=True enables Qwen3.5 chain-of-thought (slower)."""
    messages = build_prompt(perception_block, memory_context)
    response = call_ollama(messages, thinking=reasoning, timeout=60 if reasoning else 20)
    return parse_response(response) if response is not None else _FALLBACK


def reflect(perception_block: str, memory_context: str = "") -> dict:
    """Deep reflection — always uses reasoning mode."""
    messages = build_prompt(perception_block, memory_context)
    response = call_ollama(messages, thinking=True, timeout=60)
    return parse_response(response) if response is not None else _FALLBACK
