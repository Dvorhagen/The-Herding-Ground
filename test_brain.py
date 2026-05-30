#!/usr/bin/env python3
"""
test_brain.py
Run this from inside the nemo/ directory before launching main.py.
Verifies Ollama is reachable, the model responds, and the action
parser can handle the output.

Usage:
  python test_brain.py
  MORIARTY_MODEL=qwen3.5:4b python test_brain.py   # override model
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nemo.brain import moriarty_brain

FAKE_PERCEPTION = """[PERCEPTION — Tick 1]
Position: (20, 20)
Current tile: worn dirt path
  North: open grassland
  South: open grassland
  East: worn dirt path
  West: forest

Items on ground: apple
Carrying: nothing
Status: hungry, rested, feeling curious

Nearby entities:
  apple: sweet and slightly tart

Recent events:
  none"""


def test():
    print(f"Model : {moriarty_brain.MODEL}")
    print(f"URL   : {moriarty_brain.OLLAMA_URL}")
    print()

    # 1. Check Ollama is reachable
    print("1. Checking Ollama connection...")
    import requests
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        print(f"   OK — Ollama running. Available models:")
        for m in models:
            print(f"     {m}")
        if not any(moriarty_brain.MODEL in m for m in models):
            print(f"\n   WARNING: '{moriarty_brain.MODEL}' not found in available models.")
            print(f"   Run: ollama pull {moriarty_brain.MODEL}")
            sys.exit(1)
    except Exception as e:
        print(f"   FAILED — can't reach Ollama: {e}")
        print("   Make sure ollama serve is running.")
        sys.exit(1)

    print()

    # 2. Send a real perception block and get a response
    print("2. Sending test perception to Moriarty's brain...")
    result = moriarty_brain.think(FAKE_PERCEPTION)
    print(f"   Raw response:\n{'='*50}")
    print(result["raw"])
    print('='*50)

    # 3. Check parse quality
    print()
    print("3. Parsed result:")
    print(f"   THOUGHT : {result['thought']}")
    print(f"   ACTION  : {result['action']}")
    print(f"   ARGS    : {result['args']}")
    print(f"   MEMORY  : {result['memory_tool']}")

    if result["action"] == "wait" and not result["thought"]:
        print("\n   WARNING: Moriarty defaulted to wait with no thought.")
        print("   The model may not be following the output format.")
        print("   Check the raw response above.")
    else:
        print("\n   Looks good. You can run main.py.")


if __name__ == "__main__":
    test()
