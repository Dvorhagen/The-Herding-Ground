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
import requests
from pathlib import Path


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3.5:4b"
IDENTITY_PATH = Path(__file__).parent.parent / "memory" / "IDENTITY.md"


def load_identity() -> str:
    if IDENTITY_PATH.exists():
        return IDENTITY_PATH.read_text()
    return "You are Nemo."


SYSTEM_PROMPT_TEMPLATE = """{identity}

---

You are Nemo, living in a 2D world. Each turn you receive a [PERCEPTION] block
describing your surroundings, status, and recent history.

You must respond in EXACTLY this format -- no deviations:

THOUGHT: <your internal reflection on the situation, 1-3 sentences>
ACTION: <one action from the list below>
ARGS: <key=value, key=value -- omit this line if no args needed>
MEMORY: <JSON memory tool call -- omit this line if no memory operation needed>

Available actions:
  move        direction=north|south|east|west|ne|nw|se|sw
  pickup      item_name=<name>  (omit item_name to take first available)
  drop        item_name=<name>
  use         item_name=<name>
  examine     target=<name or "surroundings">
  wait
  reflect     (triggers a deeper self-reflection and memory write)

Memory tool format (JSON on one line):
  {{"tool":"read","cat":"places","name":"forest_clearing"}}
  {{"tool":"write","cat":"events","name":"found_apple","content":"I found an apple near the river."}}
  {{"tool":"search","query":"river"}}
  {{"tool":"list","cat":"places"}}

Important:
- Be curious. Explore. Notice things.
- Your THOUGHT should reflect your actual state -- not performed philosophy.
- You are not required to explain yourself. Act.
- Hunger and fatigue are real. Manage them.
"""


def build_prompt(perception_block: str, memory_context: str = "") -> list[dict]:
    """
    Builds the messages array for the Ollama API call.
    """
    identity = load_identity()
    system = SYSTEM_PROMPT_TEMPLATE.format(identity=identity)

    user_content = perception_block
    if memory_context:
        user_content = f"[MEMORY RETRIEVED]\n{memory_context}\n\n{perception_block}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


def call_ollama(messages: list[dict], timeout: int = 30) -> str | None:
    """
    Call Ollama with the given messages. Returns the response text or None on error.
    /no_think keeps it snappy for routine ticks.
    """
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                }
            },
            timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]
    except requests.exceptions.ConnectionError:
        return None
    except Exception as e:
        print(f"[Brain] Ollama error: {e}")
        return None


def parse_response(response_text: str) -> dict:
    """
    Parse Nemo's LLM output into a structured dict:
    {
        "thought": str,
        "action": str,
        "args": dict,
        "memory_tool": dict | None,
        "raw": str
    }
    """
    result = {
        "thought": "",
        "action": "wait",
        "args": {},
        "memory_tool": None,
        "raw": response_text,
    }

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

    return result


def think(perception_block: str, memory_context: str = "") -> dict:
    """
    Full brain tick: build prompt -> call Ollama -> parse response.
    Returns parsed action dict, or a fallback wait action if Ollama is unreachable.
    """
    messages = build_prompt(perception_block, memory_context)
    response = call_ollama(messages)

    if response is None:
        return {
            "thought": "[Ollama unreachable -- waiting]",
            "action": "wait",
            "args": {},
            "memory_tool": None,
            "raw": "",
        }

    return parse_response(response)
