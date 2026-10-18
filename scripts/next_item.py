#!/usr/bin/env python3
"""Print the next ticket to work on. Stdlib only.

Usage:
    python3 scripts/next_item.py [--epic <id>]

Rules (deterministic):
  1. If any non-epic ticket is `in_progress` (and not tagged needs-owner), print it (resume, never start a second one).
  2. Else candidates = status `open`, type != epic, every dep closed,
     no `needs-owner` tag, and (if --epic given) parent == epic.
  3. Sort by priority (0 first), then created timestamp, then title.
Output: `<id>\t<priority>\t<title>`; prints NONE when nothing is ready.
Progress for --epic goes to stderr, e.g. "progress: 1/4 closed".
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TICKETS = ROOT / ".tickets"


def parse(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    if not m:
        return None
    meta = {}
    for ln in m.group(1).splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            meta[k.strip()] = v.strip()
    for key in ("deps", "tags"):
        meta[key] = [x.strip() for x in meta.get(key, "[]").strip("[]").split(",") if x.strip()]
    title = re.search(r"^# (.+)$", m.group(2), re.M)
    meta["title"] = title.group(1).strip() if title else ""
    return meta


def main(argv):
    epic = argv[argv.index("--epic") + 1] if "--epic" in argv else None
    tickets = [t for t in (parse(p) for p in sorted(TICKETS.glob("*.md"))) if t and t.get("id")]
    by_id = {t["id"]: t for t in tickets}
    scope = [t for t in tickets if t.get("type") != "epic" and (epic is None or t.get("parent") == epic)]
    if epic:
        done = sum(1 for t in scope if t.get("status") == "closed")
        print(f"progress: {done}/{len(scope)} closed", file=sys.stderr)

    key = lambda t: (int(t.get("priority", 2)), t.get("created", ""), t["title"])
    active = sorted(
        (t for t in scope if t.get("status") == "in_progress" and "needs-owner" not in t["tags"]), key=key
    )
    if active:
        t = active[0]
        print(f"{t['id']}\t{t.get('priority')}\t{t['title']}")
        return 0
    ready = [
        t for t in scope
        if t.get("status") == "open"
        and "needs-owner" not in t["tags"]
        and all(by_id.get(d, {}).get("status") == "closed" for d in t["deps"])
    ]
    if not ready:
        print("NONE")
        return 0
    t = sorted(ready, key=key)[0]
    print(f"{t['id']}\t{t.get('priority')}\t{t['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
