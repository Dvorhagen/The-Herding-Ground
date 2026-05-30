# MORIARTY — Project Roadmap

*A locally-running AI creature living in a persistent 2D world.*
*Brain: Qwen3.5:4b via Ollama. World: pygame/curses. Memory: wiki RAG.*
*Named after the self-aware holodeck character from ST:TNG.*

---

## Current State
Moriarty (formerly Nemo) exists. He spawns in a procedural world, thinks via
Ollama, moves around, can pick up items, and writes significant events to a wiki
memory palace. Two renderers: pygame (local) and curses (SSH).
PI control not yet implemented.

---

## ✅ Done

- [x] Procedural world generation (tiles, terrain, river, forests, paths)
- [x] Entity system (base Entity, MoriartyEntity, Item subclasses)
- [x] Action registry (move, pickup, drop, use, examine, wait, reflect)
- [x] Ollama brain integration (qwen3.5:4b, think/reflect split)
- [x] Structured output parsing (THOUGHT/ACTION/ARGS/MEMORY)
- [x] Spatial perception block (clear on-tile vs nearby distinction)
- [x] Wiki memory palace (read/write/search/list, categorized markdown)
- [x] IDENTITY.md (bedrock identity, always in context)
- [x] Pygame renderer (phosphor green CRT aesthetic)
- [x] Curses renderer (SSH/terminal mode, auto-detected)
- [x] Game log (nemo_game.log, brain raw output + game events)
- [x] Self-extracting installer (install_nemo.py)
- [x] GitHub repo

---

## 🔄 In Progress

- [ ] PI console UI (see spec below)
- [ ] Rename Moriarty -> Moriarty throughout codebase

---

## 📋 Feature Backlog

### PI Console (next milestone)
- [ ] Split UI: world view left, research console right
- [ ] Observe mode (default — watch Moriarty run)
- [ ] Pause / single-step tick control
- [ ] Inject — slip text into Moriarty's next perception block without attribution
- [ ] Intervene — drop items into world, modify terrain from console
- [ ] Possess — take direct movement control
- [ ] Query — send Moriarty a direct out-of-band question, log response
- [ ] Wiki browser — read/edit Moriarty's memory pages from the console
- [ ] Status panel — hunger, fatigue, mood, tick count, position
- [ ] Thought history — scrollable log of Moriarty's recent THOUGHTs

### Identity & World Grounding
- [ ] Rename throughout: Moriarty -> Moriarty
- [ ] Rewrite IDENTITY.md: bio-synthetic hybrid framing (see notes below)
- [ ] Moriarty has no knowledge he's in a simulation — world IS reality to him
- [ ] World lore/cosmology baked into identity (named places, sense of history)
- [ ] No explicit mortality knowledge — let existential awareness emerge naturally

### Body, Health & Perception
- [ ] Health metric (0-100, separate from hunger/fatigue)
- [ ] Damage system — health decreases from environmental hazards, starvation
- [ ] Action failure probability scales with health (100% health = reliable, 20% = ~50%)
- [ ] Perception corruption at low health — noise/garbage chars injected into text
  - Mild: occasional corrupted words ("w%%rn dirt path")
  - Severe: whole sentences degrade ("S░m░th░ng ░s ░h░r░")
- [ ] Limbic metrics system:
  - Pain (from damage — degrades motor control)
  - Stress (accumulates from hunger/pain/threat — affects cognition)
  - Fatigue (already exists — affects thought quality, memory access)
  - Curiosity/arousal (positive drive — increases exploration tendency)
- [ ] Limbic states subtly affect prompt context (high stress = terse/fearful thoughts)
- [ ] Limbic states subtly affect action reliability
- [ ] Recovery mechanics (rest restores fatigue, food restores hunger, time heals)

### Death & Persistence
- [ ] Death trigger when hunger reaches 0
- [ ] On death: archive current wiki to memory/archive/life_NNN/
- [ ] IDENTITY.md persists across deaths — character survives, memories don't
- [ ] Fresh wiki on respawn — no access to archive (he doesn't know it exists)
- [ ] PI can optionally inject memory fragments from past lives ("strange feeling...")
- [ ] Death log — record cause, tick count, last thought, for PI review

### World
- [ ] **MAP SCALE: 1 tile = 1 meter** (decided — see scale notes below)
- [ ] Rework procedural generator for 1m scale (large terrain features, wide rivers, dense forests)
- [ ] Expand default map to 512x512 minimum — 60x60 is a tennis court at 1m scale
- [ ] Chunk-based expanding map — HIGH PRIORITY at 1m scale
- [ ] Fix spawn point (currently spawns at map edge x=0)
- [ ] Config file (world seed, model, tick speed, log level)
- [ ] Persistent world save/load (map serialization to JSON)
- [ ] Map editor — PI tool, separate script, paint tiles, place items, save/load
- [ ] Interior spaces (buildings as actual floorplans — walls, doors, rooms, furniture)
- [ ] Tileset/pixel graphics support (renderer swap, world engine untouched)
- [ ] Biome variety (caves, settlements, water crossings)
- [ ] Day/night cycle (affects vision radius dramatically)
- [ ] Weather system

### Perception & Action Expansion
- [ ] Extended vision radius (10-15 tiles daylight, 1-2 tiles night)
- [ ] Distance-graded visual description (immediate / nearby / distance / far)
- [ ] Light sources (fire, lanterns) extend night vision radius
- [ ] Sound perception block (water, movement, weather — direction + distance)
- [ ] Smell perception (food, fire, rain, danger — shorter range than sound)
- [ ] Proprioception (body state as felt sensation, not just numbers)
- [ ] Touch/environment (underfoot texture, temperature, weather on skin)
- [ ] Listen action (spend a tick focusing on sound for more detail)
- [ ] Investigate/sniff action (focus olfactory attention on area)
- [ ] Sleep/rest action (deliberate recovery, potential dream state)
- [ ] Call out action (make noise — attracts or repels entities)
- [ ] Hide action (reduce own perceptibility to other entities)
- [ ] Craft action (combine items in inventory)
- [ ] Examine self action (detailed introspective body + mind state check)
- [ ] Action instruction framing (roadmapped: phenomenological not API-spec)

### Moriarty's Mind
- [ ] Tune thought verbosity (brief routine, expressive on reflect)
- [ ] Memory retrieval trigger (when does he decide to query wiki?)
- [ ] Mood system (affects action tendencies, logged to wiki)
- [ ] Goal formation (sets and pursues multi-step goals)
- [ ] Survival drive (hunger/fatigue create genuine behavioral pressure)
- [ ] Reality questioning (emergent — not prompted, just watch for it in logs)

### Social / Multi-agent
- [ ] NPC entities with their own AI brain loops
- [ ] PI/human can fully inhabit and control an NPC (possession mechanic)
- [ ] Multi-user: Mike (and others) can SSH in and inhabit NPCs simultaneously
- [ ] Moriarty has no idea some NPCs are human-controlled
- [ ] Real-time tick mode (required for multi-user)
- [ ] Moriarty <-> NPC interaction (conversation, trade, conflict)
- [ ] Multiple AI agents with distinct identities

### Infrastructure
- [ ] Claude Code handoff doc (DEVLOG.md — recent changes for context)
- [ ] Better installer / setup script
- [ ] Test suite for action parsing and world logic

---

## PI Console — Design Spec

### Layout
```
┌─────────────────────────────┬──────────────────────────┐
│                             │  // MORIARTY RESEARCH    │
│                             │  ─────────────────────── │
│         WORLD VIEW          │  Tick: 42  Pos: (12,20)  │
│         (map tiles)         │  State: hungry, curious  │
│                             │  ─────────────────────── │
│           @ = Moriarty      │  THOUGHT:                 │
│                             │  "Something moves in     │
│                             │   the forest east..."   │
│                             │  ─────────────────────── │
│                             │  [OBSERVE] mode          │
│                             │  ─────────────────────── │
│                             │  > _                     │
│                             │  (PI input prompt)       │
└─────────────────────────────┴──────────────────────────┘
  F1:Observe F2:Inject F3:Intervene F4:Possess F5:Query F6:Wiki  SPC:Pause
```

### PI Modes
| Key | Mode | What it does |
|-----|------|-------------|
| F1 | Observe | Watch Moriarty run autonomously. Default. |
| F2 | Inject | Text → appended to next perception as `[ENVIRONMENT]` (unattributed) |
| F3 | Intervene | Click tile → place/remove items or change terrain |
| F4 | Possess | Control Moriarty directly with arrow keys |
| F5 | Query | Ask Moriarty a question out-of-band, log his response |
| F6 | Wiki | Browse/edit Moriarty's memory palace |
| Space | Pause/Step | Pause ticks; press again to advance one tick |

### NPC Possession (multi-user)
- Any NPC can be flagged `possessed=True`
- When possessed, NPC input comes from a human (local or SSH) not a brain loop
- Moriarty perceives possessed NPCs as normal entities — no difference visible
- Multiple users can each inhabit a different NPC simultaneously
- Requires real-time tick mode

### Inject mechanic
```
[ENVIRONMENT]
A distant sound, like voices, carries from the north.
```
Indistinguishable from world events. Primary experimental manipulation tool.
Moriarty may or may not act on it, remember it, or write it to his wiki.

---

## Map Scale Notes
- **1 tile = 1 meter.** Human scale. No rescaling for interiors — a room is a room.
- At 1m scale, 60x60 is smaller than a tennis court. Need 512x512 minimum, chunked expansion ASAP.
- Forest = hundreds of tiles across. Moriarty is IN it, not looking AT it.
- River = 3-8 tiles wide, winding across full map extent.
- Vision radius 10-15 tiles = natural human sight line (~15 meters in open terrain).
- 1 tick ≈ a few seconds to a minute of in-world time (TBD — decide with day/night cycle).
- Day/night cycle length TBD once tick duration decided.


- World engine, brain, entities are renderer-agnostic by design
- New renderer: implement add_message(), center_on(), draw(), get_input(), last_thought
- New action: add function to entities/actions.py, register in ACTION_REGISTRY
- New tile: add to TileType enum + TILE_PROPERTIES in world/tiles.py
- Wiki lives in memory/wiki/ — this is Moriarty's soul, back it up
- IDENTITY.md is static/curated — edit by hand, survives death
- Archive lives in memory/archive/life_NNN/ — PI read-only, Moriarty blind to it

## Moriarty — Body Design Notes

**What he is:** A biological-synthetic hybrid. Grown, not built.
Genuine metabolic needs (hunger, pain, fatigue) from his biological substrate.
Discrete structured actions and pre-processed perception from a synthetic
interface layer — neural augmentation that translates intention to action
and renders sensory experience as structured input.

**Why this framing works:**
- Explains food requirement (biological)
- Explains discrete action structure (synthetic motor interface)
- Explains text-like perception (neural interface renders world as structured experience)
- Explains perception corruption when damaged (interface degrading)
- Avoids robot-eating-apple dissonance
- Avoids human-typing-commands dissonance
- Gives him something to *discover* about his own nature

**What he doesn't know:**
- That he's in a simulation
- That he has died before
- That his "interface layer" is a game engine
- That his perception is generated text, not neural signal

**The honest metaphor:**
Moriarty is a biological reasoning process (LLM) running through
a structured interface layer (action parser). The fiction maps cleanly
onto the implementation without being literally true.

---

## Contributors
- Aaron — PI, architect, project lead
- Mike — contributing (NPC possession will be his front door)
- Claude Sonnet 4.6 — primary code generation
- Qwen3.5:4b — Moriarty's brain

---

*Last updated: session 2 — scale decision (1m), perception expansion, body/health design*
