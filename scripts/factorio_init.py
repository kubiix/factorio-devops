#!/usr/bin/env python3
"""Initialize a fresh Factorio mod repository from its initPending template state."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
CATEGORIES = {"no-category", "content", "overhaul", "tweaks", "utilities", "scenarios", "mod-packs", "localizations", "internal"}
TAGS = {"transportation", "logistics", "trains", "combat", "armor", "enemies", "environment", "mining", "fluids", "logistic-network", "circuit-network", "manufacturing", "power", "storage", "blueprints", "cheats"}
MIT = """MIT License

Copyright (c) {year} kubiix@live.com

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


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


def main(root: Path, devops: Path) -> None:
    internal_name = env("INTERNAL_NAME")
    mod_title = env("MOD_TITLE")
    display_name = env("DISPLAY_NAME")
    version = env("INITIAL_VERSION")
    license_name = env("MOD_LICENSE")
    category = env("CATEGORY")
    tags = [tag.strip() for tag in env("TAGS", required=False).split(",") if tag.strip()]
    description, faq, summary = env("DESCRIPTION"), env("FAQ", required=False), env("SUMMARY", required=False)
    if not NAME_RE.fullmatch(internal_name):
        fail("internal_name may contain only lowercase letters, digits, hyphens, and underscores")
    if not VERSION_RE.fullmatch(version):
        fail("initial_version must be numeric major.minor.patch")
    if license_name != "MIT":
        fail("only MIT is currently supported")
    if len(display_name) > 250:
        fail("display_name must not exceed 250 characters")
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
    state.update({"versionState": "development", "versionLine": version_line, "portalState": "unpublished"})
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    info_path = root / "src" / "info.json"
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read src/info.json: {exc}")
    info.update({"name": internal_name, "title": mod_title, "version": version, "author": "kubiix"})
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    changelog_path = root / "src" / "changelog.txt"
    changelog = changelog_path.read_text(encoding="utf-8")
    changelog, substitutions = re.subn(r"(?m)^Version:\s*\d+\.\d+\.x\s*$", f"Version: {version_line}", changelog, count=1)
    if substitutions != 1 or not re.search(r"(?m)^Date:\s*TBD\s*$", changelog):
        fail("src/changelog.txt must contain an initial numeric .x version and Date: TBD")
    changelog_path.write_text(changelog, encoding="utf-8")

    year = str(datetime.now(UTC).year)
    license_text = MIT.format(year=year)
    (root / "LICENSE").write_text(license_text, encoding="utf-8")
    (root / "src" / "LICENSE").write_text(license_text, encoding="utf-8")
    copyright_template = (devops / "COPYRIGHT" / "NEW_MOD").read_text(encoding="utf-8")
    (root / "src" / "COPYRIGHT").write_text(copyright_template.replace("{{YEAR}}", year).replace("{{AUTHOR}}", "kubiix@live.com").replace("{{LICENSE_NOTICE}}", "Licensed under the MIT License."), encoding="utf-8")

    portal = {"title": display_name, "category": category, "license": "default_mit"}
    if tags:
        portal["tags"] = tags
    content = root / "modPortalContent"
    content.mkdir(exist_ok=True)
    (content / "description.md").write_text(description + "\n", encoding="utf-8")
    (content / "portalInfo.json").write_text(json.dumps(portal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if faq:
        (content / "faq.md").write_text(faq + "\n", encoding="utf-8")
    if summary:
        (content / "summary.txt").write_text(summary + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        fail("usage: factorio_init.py ROOT DEVOPS_ROOT")
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
