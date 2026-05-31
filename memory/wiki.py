"""
memory/wiki.py
Moriarty's Memory Palace -- a wiki-style persistent memory store.
Each memory is a markdown file in the wiki directory.
Moriarty can read and write pages as a tool call.

Pages are organized by category:
  - places/     : locations Moriarty has been
  - entities/   : creatures, people, things encountered
  - events/     : significant things that happened
  - self/       : Moriarty's self-model (updated via reflection)

This keeps the RAG context cheap: retrieve only what's relevant,
not the whole memory.
"""

import os
import json
from datetime import datetime
from pathlib import Path


WIKI_DIR = Path(__file__).parent / "wiki"


def _ensure_dirs():
    for cat in ["places", "entities", "events", "self"]:
        (WIKI_DIR / cat).mkdir(parents=True, exist_ok=True)


def _sanitize_name(name: str) -> str:
    """Convert a page name to a safe filename."""
    return name.lower().replace(" ", "_").replace("/", "-")


def read_page(category: str, name: str) -> str | None:
    """
    Read a wiki page. Returns content string or None if not found.
    category: 'places', 'entities', 'events', 'self'
    name: page name (will be sanitized)
    """
    _ensure_dirs()
    path = WIKI_DIR / category / f"{_sanitize_name(name)}.md"
    if path.exists():
        return path.read_text()
    return None


def write_page(category: str, name: str, content: str, append: bool = False):
    """
    Write or update a wiki page.
    append=True adds content rather than replacing.
    """
    _ensure_dirs()
    path = WIKI_DIR / category / f"{_sanitize_name(name)}.md"
    if append and path.exists():
        existing = path.read_text()
        content = existing + "\n\n" + content
    path.write_text(content)


def list_pages(category: str = None) -> list[str]:
    """List available pages, optionally filtered by category."""
    _ensure_dirs()
    if category:
        cat_dir = WIKI_DIR / category
        if not cat_dir.exists():
            return []
        return [f.stem for f in cat_dir.glob("*.md")]
    pages = []
    for cat in ["places", "entities", "events", "self"]:
        cat_dir = WIKI_DIR / cat
        if cat_dir.exists():
            for f in cat_dir.glob("*.md"):
                pages.append(f"{cat}/{f.stem}")
    return pages


def search_pages(query: str) -> list[tuple[str, str]]:
    """
    Simple keyword search across all wiki pages.
    Returns list of (path_str, snippet) for pages containing the query.
    """
    _ensure_dirs()
    query_lower = query.lower()
    results = []
    for cat in ["places", "entities", "events", "self"]:
        cat_dir = WIKI_DIR / cat
        if not cat_dir.exists():
            continue
        for f in cat_dir.glob("*.md"):
            content = f.read_text()
            if query_lower in content.lower():
                # Extract a brief snippet around the first match
                idx = content.lower().find(query_lower)
                start = max(0, idx - 60)
                end = min(len(content), idx + 120)
                snippet = content[start:end].replace("\n", " ")
                results.append((f"{cat}/{f.stem}", snippet))
    return results


def record_event(tick: int, description: str, tags: list[str] = None):
    """
    Convenience: write a timestamped event to the events category.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    tags_str = ", ".join(tags) if tags else "general"
    content = f"""# Event: Tick {tick}
*Recorded: {timestamp}*
*Tags: {tags_str}*

{description}
"""
    write_page("events", f"tick_{tick:05d}", content)


def get_self_model() -> str:
    """Read Moriarty's current self-model page."""
    content = read_page("self", "current")
    if content:
        return content
    # Initialize with stub
    default = """# Moriarty — Self Model
*This page is updated by Moriarty through reflection.*

## What I know about myself so far
I am new. I am beginning.

## Things I have noticed about how I think
(not yet recorded)

## Things that feel important
(not yet recorded)
"""
    write_page("self", "current", default)
    return default


def update_self_model(new_content: str):
    """Replace Moriarty's self-model with updated content."""
    write_page("self", "current", new_content)


# --- Tool interface for Moriarty's brain ---
# These functions are called when Moriarty's LLM output includes a MEMORY_TOOL block

MEMORY_TOOLS = {
    "read":   lambda category, name, **_: read_page(category, name) or f"No page found: {category}/{name}",
    "write":  lambda category, name, content, **kw: (write_page(category, name, content, kw.get("append", False)), "Page written.")[1],
    "list":   lambda category=None, **_: "\n".join(list_pages(category)),
    "search": lambda query, **_: "\n".join(f"{p}: ...{s}..." for p, s in search_pages(query)) or "No results.",
}


def execute_memory_tool(tool_call: dict) -> str:
    """
    Execute a memory tool call from Moriarty's output.
    tool_call: {"tool": "read"|"write"|"list"|"search", ...args}
    Returns the result as a string.
    """
    tool = tool_call.get("tool")
    if tool not in MEMORY_TOOLS:
        return f"Unknown memory tool: '{tool}'. Available: {list(MEMORY_TOOLS.keys())}"
    try:
        return MEMORY_TOOLS[tool](**{k: v for k, v in tool_call.items() if k != "tool"})
    except Exception as e:
        return f"Memory tool error: {e}"
