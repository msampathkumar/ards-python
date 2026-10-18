#!/usr/bin/env python3
"""Layer-A gate for a code change in ards-python. Stdlib only.

Usage:
    python3 scripts/validate_change.py                 # diff vs origin/master (committed + working tree + untracked)
    python3 scripts/validate_change.py --base <ref>    # diff vs another ref
    python3 scripts/validate_change.py --all           # audit whole repo (every file treated as changed)

Checks (patterns live in standards/engineering.md):
  1. All Python under ards/, tests/, scripts/ compiles.
  2. pytest passes (uses .venv/bin/python if present).
  3. A change under ards/ includes a changed tests/test_*.py.
  4. A change under ards/ includes a .tickets/ change.
  5. Added lines contain no forbidden code / secret / test-network patterns.
  6. Changed ards/ files contain no `except ...:` followed directly by `pass`.
Exit 0 = pass. One line per violation.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STANDARD = ROOT / "standards" / "engineering.md"


def sh(*args, check=False):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=check)


def block(text, tag):
    m = re.search(r"```" + re.escape(tag) + r"\n(.*?)```", text, re.S)
    if not m:
        sys.exit(f"CONFIG ERROR: ```{tag} block missing in {STANDARD}")
    return [re.compile(p.strip()) for p in m.group(1).splitlines() if p.strip()]


def changed_files_and_added_lines(base, audit_all):
    """Return (set of changed paths, {path: [added lines]})."""
    if audit_all:
        files = [f for f in sh("git", "ls-files").stdout.splitlines()]
        added = {}
        for f in files:
            p = ROOT / f
            if p.suffix in (".py", ".md", ".toml", ".txt", ".json", ".yaml", ".yml", ".html") and p.exists():
                added[f] = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return set(files), added
    if sh("git", "rev-parse", "--verify", "--quiet", base).returncode != 0:
        sys.exit(f"base ref '{base}' not found; run `git fetch` or pass --base <ref>")
    names = set(sh("git", "diff", "--name-only", base).stdout.split())
    untracked = set(sh("git", "ls-files", "--others", "--exclude-standard").stdout.split())
    added = {}
    cur = None
    for ln in sh("git", "diff", "-U0", base).stdout.splitlines():
        if ln.startswith("+++ "):
            cur = ln[6:] if ln.startswith("+++ b/") else None
            if cur:
                added.setdefault(cur, [])
        elif ln.startswith("+") and cur:
            added[cur].append(ln[1:])
    for f in untracked:
        p = ROOT / f
        if p.is_file():
            added[f] = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return names | untracked, added


def main(argv):
    audit_all = "--all" in argv
    base = argv[argv.index("--base") + 1] if "--base" in argv else "origin/master"
    std = STANDARD.read_text(encoding="utf-8")
    pats = {
        "code": block(std, "forbidden-code"),
        "secrets": block(std, "forbidden-secrets"),
        "tests": block(std, "forbidden-tests"),
    }
    errs = []

    # 1. compile
    r = sh(sys.executable, "-m", "compileall", "-q", "ards", "tests", "scripts")
    if r.returncode != 0:
        errs.append("compile: " + (r.stdout + r.stderr).strip().splitlines()[-1])

    # 2. pytest
    py = ROOT / ".venv" / "bin" / "python"
    py = str(py) if py.exists() else sys.executable
    r = sh(py, "-m", "pytest", "-q", "-p", "no:cacheprovider")
    tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or ["no output"]
    if r.returncode != 0:
        errs.append(f"pytest: exit {r.returncode}: {tail[0]}  (setup: pip install -e '.[dev]')")
    else:
        print(f"pytest: {tail[0]}")

    changed, added = changed_files_and_added_lines(base, audit_all)
    code_changed = sorted(f for f in changed if f.startswith("ards/") and f.endswith(".py"))

    if not audit_all and code_changed:
        # 3. tests accompany code
        if not any(re.match(r"tests/(.*/)?test_[^/]+\.py$", f) for f in changed):
            errs.append(f"tests: ards/ changed ({', '.join(code_changed)}) but no tests/test_*.py changed")
        # 4. ticket trail
        if not any(f.startswith(".tickets/") for f in changed):
            errs.append("tickets: ards/ changed but no .tickets/ change (run tk start/add-note)")

    # 5. forbidden patterns in added lines
    for f, lines in sorted(added.items()):
        if f.startswith("standards/"):
            continue  # pattern definitions live here
        groups = ["secrets"]
        if f.startswith("ards/") and f.endswith(".py"):
            groups.append("code")
        if f.startswith("tests/") and f.endswith(".py"):
            groups.append("tests")
        for ln in lines:
            for g in groups:
                for rx in pats[g]:
                    if rx.search(ln):
                        shown = "<redacted>" if g == "secrets" else ln.strip()[:80]
                        errs.append(f"{g}: {f}: /{rx.pattern}/ in: {shown}")

    # 6. swallowed exceptions in changed ards/ files
    swallow = re.compile(r"^[ \t]*except\b[^\n]*:[ \t]*(#[^\n]*)?\n([ \t]*#[^\n]*\n)*[ \t]*pass\b", re.M)
    for f in code_changed:
        p = ROOT / f
        if p.exists():
            for m in swallow.finditer(p.read_text(encoding="utf-8")):
                line = p.read_text(encoding="utf-8")[: m.start()].count("\n") + 1
                errs.append(f"swallowed-exception: {f}:{line}: log it (standards/engineering.md code rule 3)")

    for e in errs:
        print(e)
    scope = "all files" if audit_all else f"diff vs {base}"
    print(f"{'PASS' if not errs else 'FAIL'} validate_change ({scope}; {len(errs)} violations)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
