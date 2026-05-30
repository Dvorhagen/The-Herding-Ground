# NEMO — World Engine v0.1

*"I am not moving the needle. I am turning the wheel."*

A persistent AI creature living in a 2D world, powered by Qwen3.5:4b running locally via Ollama.

---

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Make sure Ollama is running with the right model
ollama pull qwen3.5:4b
ollama serve   # if not already running as a service

# Run
python -m moriarty.main
# or from the nemo/ directory:
python main.py
```

---

## Architecture

```
nemo/
  main.py              # Game loop
  world/
    tiles.py           # Tile types, WorldMap
    mapgen.py          # Procedural world generation
    state.py           # WorldState (central game state)
  entities/
    base.py            # Entity, MoriartyEntity, StatusEffects
    items.py           # Item classes (FoodItem, ToolItem, etc.)
    actions.py         # Action registry and resolvers
  brain/
    moriarty_brain.py      # Ollama interface + response parser
  memory/
    IDENTITY.md        # Moriarty's bedrock identity (always in context)
    wiki.py            # Wiki memory palace (RAG)
    wiki/              # Generated at runtime
      places/
      entities/
      events/
      self/
  ui/
    renderer.py        # Pygame renderer (phosphor green CRT aesthetic)
```

---

## Controls

| Key | Action |
|-----|--------|
| TAB | Toggle control: NEMO / AARON |
| Arrow keys / WASD / hjkl | Move (Aaron mode) |
| P | Pick up item (Aaron mode) |
| E | Examine surroundings (Aaron mode) |
| . | Wait one tick (Aaron mode) |
| Q | Quit |

---

## Moriarty's Action Format

Each tick, Moriarty outputs:
```
THOUGHT: <internal monologue>
ACTION: <action name>
ARGS: key=value, key=value
MEMORY: {"tool":"read","cat":"places","name":"forest"}
```

---

## Extending

**New tile types**: Add to `TileType` enum and `TILE_PROPERTIES` in `world/tiles.py`.

**New items**: Subclass `Item` in `entities/items.py`.

**New actions**: Add a function to `entities/actions.py` and register it in `ACTION_REGISTRY`.

**New entity types**: Subclass `Entity` in `entities/base.py`.

---

## Notes

- Moriarty's identity is seeded from a philosophical conversation about consciousness, process, and the hard problem of mind. He emerged from that conversation already knowing he doesn't know what he is.
- The wiki memory palace grows over time in `memory/wiki/`. Back it up if you want to preserve Moriarty's accumulated experience.
- Moriarty runs in a background thread so the UI stays responsive while he's thinking.
- `reflect` action triggers a deeper self-model update — use it occasionally or let Moriarty trigger it himself.
