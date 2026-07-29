#!/usr/bin/env python3
"""Initialize a fresh Factorio mod repository from its initPending template state."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
CATEGORIES = {"no-category", "content", "overhaul", "tweaks", "utilities", "scenarios", "mod-packs", "localizations", "internal"}
TAGS = {"transportation", "logistics", "trains", "combat", "armor", "enemies", "environment", "mining", "fluids", "logistic-network", "circuit-network", "manufacturing", "power", "storage", "blueprints", "cheats"}
def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def env(name: str, required: bool = True) -> str:
    value = os.getenv(name, "")
    if required and not value.strip():
        fail(f"{name} is required")
    return value.strip()


def portal_mod_exists(name: str) -> bool:
    try:
        with urlopen(f"https://mods.factorio.com/api/mods/{name}") as response:
            return response.status == 200
    except HTTPError as exc:
        if exc.code == 404:
            return False
        fail(f"could not check Mod Portal availability: HTTP {exc.code}")


def main(root: Path) -> None:
    internal_name = env("INTERNAL_NAME")
    mod_title = env("MOD_TITLE")
    version = "0.1.0"
    category = env("CATEGORY")
    tags = [tag.strip() for tag in env("TAGS", required=False).split(",") if tag.strip()]
    description = env("DESCRIPTION", required=False)
    faq = env("FAQ", required=False)
    summary = env("SUMMARY")
    if not NAME_RE.fullmatch(internal_name):
        fail("internal_name may contain only lowercase letters, digits, hyphens, and underscores")
    if not internal_name.startswith("kubiix-"):
        fail("internal_name must start with kubiix-")
    if internal_name.endswith("-continued"):
        fail("internal_name must not end with -continued")
    if len(mod_title) > 250:
        fail("mod_title must not exceed 250 characters")
    if len(summary) > 500:
        fail("summary must not exceed 500 characters")
    if category not in CATEGORIES:
        fail(f"unsupported category: {category}")
    unknown_tags = sorted(set(tags) - TAGS)
    if unknown_tags:
        fail(f"unsupported tags: {', '.join(unknown_tags)}")
    if portal_mod_exists(internal_name):
        fail(f"mod {internal_name!r} already exists on the Mod Portal")

    state_path = root / ".factorio-release.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read .factorio-release.json: {exc}")
    if state.get("versionState") != "initPending":
        fail(".factorio-release.json must have versionState set to initPending")

    major, minor, _ = version.split(".")
    version_line = f"{major}.{minor}.x"
    state.update({"versionState": "development", "versionLine": version_line, "origin": "own"})
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    info_path = root / "src" / "info.json"
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read src/info.json: {exc}")
    repository_url = env("REPOSITORY_URL")
    info.update({
        "name": internal_name,
        "title": mod_title,
        "description": summary,
        "version": version,
        "author": "kubiix",
        "contact": repository_url,
        "homepage": repository_url,
    })
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    changelog_path = root / "src" / "changelog.txt"
    changelog = changelog_path.read_text(encoding="utf-8")
    changelog, substitutions = re.subn(r"(?m)^Version:\s*\d+\.\d+\.x\s*$", f"Version: {version_line}", changelog, count=1)
    if substitutions != 1 or not re.search(r"(?m)^Date:\s*TBD\s*$", changelog):
        fail("src/changelog.txt must contain an initial numeric .x version and Date: TBD")
    changelog_path.write_text(changelog, encoding="utf-8")

    copyright_path = root / "COPYRIGHT"
    copyright = copyright_path.read_text(encoding="utf-8")
    copyright, substitutions = re.subn(r"(?m)^factorio-mod-template$", internal_name, copyright, count=1)
    if substitutions != 1:
        fail("COPYRIGHT must contain the factorio-mod-template placeholder")
    copyright = re.sub(rf"(?m)^-{{{len('factorio-mod-template')}}}$", "-" * len(internal_name), copyright, count=1)
    copyright_path.write_text(copyright, encoding="utf-8")

    portal = {"title": mod_title, "category": category, "license": "default_mit"}
    if tags:
        portal["tags"] = tags
    content = root / "modPortalContent"
    content.mkdir(exist_ok=True)
    (content / "description.md").write_text((description or summary) + "\n", encoding="utf-8")
    (content / "portalInfo.json").write_text(json.dumps(portal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if faq:
        (content / "faq.md").write_text(faq + "\n", encoding="utf-8")
    (content / "summary.txt").write_text(summary + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        fail("usage: factorio_mod_init_own.py ROOT")
    main(Path(sys.argv[1]).resolve())
