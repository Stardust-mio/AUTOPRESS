"""Check the file-ownership table in SPEC.md against the files on disk (OWNED BY A1).

    .venv/Scripts/python.exe tools/check_ownership.py            # report, exit 1 on problems

Rules checked:
1. every table row names an owner in OWNERS; no path/glob row appears twice;
2. every project file (outside .venv, .git, docs/research, caches, build output, runtime data)
   matches exactly ONE row;
3. a file whose first line is "# OWNED BY Gx ..." matches a row owned by Gx;
4. every explicit (non-glob) row owned by A1 exists.
Rows are Markdown table lines whose first cell holds one or more back-ticked paths or globs
(fnmatch syntax, "/" separators, "*" may cross folders) and whose second cell is the owner.
"""

from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNERS = {"A1", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "USER", "RESEARCH", "ORCH"}
SKIP_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", "build", "dist", "data", "logs", ".claude", ".idea", ".vscode"}
SKIP_PREFIXES = ("docs/research/",)
ROW = re.compile(r"^\|\s*((?:`[^`]+`[\s,]*)+)\|\s*([A-Z0-9]+)\s*\|")


def table_rows(spec: Path) -> list[tuple[str, str, int]]:
    """(path-or-glob, owner, line) for every back-ticked path in the first cell of a table row."""
    rows = []
    for n, line in enumerate(spec.read_text(encoding="utf-8").splitlines(), 1):
        m = ROW.match(line)
        if m:
            for pat in re.findall(r"`([^`]+)`", m.group(1)):
                rows.append((pat.strip(), m.group(2).strip(), n))
    return rows


def project_files() -> list[str]:
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts) or rel.startswith(SKIP_PREFIXES):
            continue
        if rel.endswith((".pyc", ".tmp")) or ".bak-" in rel or ".broken-" in rel:
            continue
        out.append(rel)
    return sorted(out)


def main() -> int:
    spec = ROOT / "SPEC.md"
    rows = table_rows(spec)
    problems: list[str] = []
    seen: dict[str, int] = {}
    for pat, owner, n in rows:
        if owner not in OWNERS:
            problems.append(f"SPEC.md:{n}: unknown owner {owner!r} for {pat}")
        if pat in seen:
            problems.append(f"SPEC.md:{n}: {pat} listed twice (also line {seen[pat]})")
        seen[pat] = n
    for rel in project_files():
        hits = [(pat, owner) for pat, owner, _n in rows if fnmatch.fnmatchcase(rel, pat)]
        if not hits:
            problems.append(f"{rel}: no owner in SPEC.md")
            continue
        if len(hits) > 1:
            problems.append(f"{rel}: matched by {len(hits)} rows: {hits}")
        if rel.endswith(".py"):
            first = (ROOT / rel).read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
            m = re.match(r"# OWNED BY (G\d)", first)
            if m and all(owner != m.group(1) for _p, owner in hits):
                problems.append(f"{rel}: header says {m.group(1)}, table says {[o for _p, o in hits]}")
    for pat, owner, n in rows:
        if owner == "A1" and not any(c in pat for c in "*?[") and not (ROOT / pat).exists():
            problems.append(f"SPEC.md:{n}: A1 file {pat} does not exist")
    for p in problems:
        print(p)
    print(f"{len(rows)} rows, {len(project_files())} files, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
