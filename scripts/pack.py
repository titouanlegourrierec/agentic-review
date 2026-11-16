#!/usr/bin/env python3
"""Pack the plugin into dist/agentic-review-<version>.zip, ready to attach to a release.

The zip holds one folder that is a complete local marketplace: .claude-plugin/marketplace.json, the plugin
(without its tests and evals), README, LICENSE and CHANGELOG. Unzip it, then:

    claude plugin marketplace add ./agentic-review-<version>
    claude plugin install agentic-review@agentic-review

Checks first that plugin.json, marketplace.json, pyproject.toml and CHANGELOG.md agree on the version (and with
--tag, that the tag is v<version>). --notes FILE writes that version's CHANGELOG section, for the release notes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "agentic-review"
LEFT_OUT_DIRS = {"tests", "evals", "__pycache__", ".pytest_cache", ".ruff_cache"}
LEFT_OUT_FILES = {".DS_Store"}


def versions() -> dict[str, str | None]:
    plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    py = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    top = re.search(r"(?m)^## \[?v?(\d+\.\d+\.\d+)", changelog)
    names = {plugin.get("name"), *(p.get("name") for p in market.get("plugins", []))}
    if names != {market.get("name")}:
        sys.exit(f"plugin and marketplace names differ: {sorted(map(str, names))} vs {market.get('name')}")
    return {
        "plugin.json": plugin.get("version"),
        "pyproject.toml": py.group(1) if py else None,
        "CHANGELOG.md (latest)": top.group(1) if top else None,
    }


def changelog_section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"(?ms)^## \[?v?{re.escape(version)}\]?[^\n]*\n(.*?)(?=^## |\Z)", text)
    return m.group(1).strip() + "\n" if m else ""


def files_to_pack() -> list[tuple[Path, str]]:
    out = [(ROOT / ".claude-plugin" / "marketplace.json", ".claude-plugin/marketplace.json")]
    for name in ("README.md", "LICENSE", "CHANGELOG.md"):
        out.append((ROOT / name, name))
    for f in sorted(PLUGIN.rglob("*")):
        rel = f.relative_to(PLUGIN)
        if not f.is_file() or f.name in LEFT_OUT_FILES or set(rel.parts) & LEFT_OUT_DIRS or f.suffix == ".pyc":
            continue
        out.append((f, f"plugins/agentic-review/{rel.as_posix()}"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", help="the git tag being released; must be v<version>")
    ap.add_argument("--notes", metavar="FILE", help="write this version's CHANGELOG section to FILE")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="output folder (default dist/)")
    args = ap.parse_args(argv)

    found = versions()
    version = found["plugin.json"]
    if not version or len(set(found.values())) != 1:
        sys.exit("versions disagree: " + ", ".join(f"{k} {v}" for k, v in found.items()))
    if args.tag and args.tag != f"v{version}":
        sys.exit(f"tag {args.tag} does not match the version {version} (expected v{version})")
    notes = changelog_section(version)
    if not notes:
        sys.exit(f"CHANGELOG.md has no section for {version}")

    name = f"agentic-review-{version}"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for src, rel in files_to_pack():
            info = zipfile.ZipInfo.from_file(src, f"{name}/{rel}")
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, src.read_bytes())
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (out_dir / f"{name}.zip.sha256").write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    if args.notes:
        Path(args.notes).write_text(notes, encoding="utf-8")
    print(f"{zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB, sha256 {digest[:12]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
