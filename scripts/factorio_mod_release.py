#!/usr/bin/env python3
"""State transitions and packaging for the reusable Factorio release workflow."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read {path}: {exc}")


def version_tuple(version: str) -> tuple[int, int, int]:
    if not VERSION_RE.fullmatch(version):
        fail(f"version must be numeric major.minor.patch, got {version!r}")
    return tuple(map(int, version.split(".")))  # type: ignore[return-value]


def files(root: Path) -> tuple[Path, Path, Path]:
    return root / "src" / "info.json", root / "src" / "changelog.txt", root / ".factorio-release.json"


def placeholder(version_line: str) -> str:
    return f"""---------------------------------------------------------------------------------------------------
Version: {version_line}
Date: TBD
Changes:
  - 

"""


def placeholder_block(text: str, version_line: str) -> tuple[int, int]:
    match = re.search(rf"(?m)^Version:\s*{re.escape(version_line)}\s*$", text)
    if not match:
        fail(f"top changelog record must contain 'Version: {version_line}'")
    start = text.rfind("---------------------------------------------------------------------------------------------------", 0, match.start())
    if start < 0:
        start = match.start()
    date = re.search(r"(?m)^Date:\s*TBD\s*$", text[match.end():])
    if not date:
        fail("development changelog record must contain 'Date: TBD'")
    next_marker = text.find("---------------------------------------------------------------------------------------------------", match.end())
    return start, len(text) if next_marker < 0 else next_marker


def prepare(root: Path, version: str) -> None:
    info_path, changelog_path, state_path = files(root)
    info, state = read_json(info_path), read_json(state_path)
    version_line = state.get("versionLine")
    if state.get("versionState") != "development" or not isinstance(version_line, str) or not re.fullmatch(r"\d+\.\d+\.x", version_line):
        fail(".factorio-release.json must mark development and contain a numeric versionLine ending in .x")
    if version.rsplit(".", 1)[0] + ".x" != version_line:
        fail(f"release version must be on the {version_line} line")
    old = info.get("version")
    if not isinstance(old, str) or version_tuple(version) < version_tuple(old):
        fail("release version must be greater or equal than src/info.json version")
    changelog = changelog_path.read_text(encoding="utf-8")
    start, end = placeholder_block(changelog, version_line)
    record = changelog[start:end]
    if not re.search(r"(?m)^\s*-\s*\S", record):
        fail("development changelog record has no change item")
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    record = re.sub(rf"(?m)^Version:\s*{re.escape(version_line)}\s*$", f"Version: {version}", record, count=1)
    record = re.sub(r"(?m)^Date:\s*TBD\s*$", f"Date: {date}", record, count=1)
    # The tagged commit contains only published records.  The following commit
    # restores the development placeholder after the external uploads succeed.
    changelog_path.write_text(record + changelog[end:], encoding="utf-8")
    info["version"] = version
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    state["versionState"] = "release"
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    notes = re.sub(r"^-+\n", "", record).strip() + "\n"
    (root / ".release-notes.md").write_text(notes, encoding="utf-8")


def build(root: Path, version: str) -> None:
    info_path, changelog_path, _ = files(root)
    info = read_json(info_path)
    name = info.get("name")
    if not isinstance(name, str) or not name:
        fail("src/info.json must contain a non-empty internal name")
    if info.get("version") != version:
        fail("src/info.json does not contain the requested release version")
    tag = f"v{version}"
    prefix = f"{name}_{version}"
    dist = root / "dist"
    stage = root / ".release-stage" / prefix
    shutil.rmtree(stage.parent, ignore_errors=True)
    stage.mkdir(parents=True)
    archive = subprocess.run(["git", "archive", "--format=tar", f"{tag}:src"], cwd=root, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=__import__("io").BytesIO(archive), mode="r:") as source:
        source.extractall(stage, filter="data")
    for document in ("LICENSE", "COPYRIGHT"):
        candidate = root / document
        if candidate.exists():
            shutil.copy2(candidate, stage / document)
    changelog = subprocess.run(["git", "show", f"{tag}:src/changelog.txt"], cwd=root, check=True, capture_output=True, text=True).stdout
    if re.search(r"(?m)^Version:\s*\d+\.\d+\.x\s*$", changelog):
        fail("tagged release changelog must not contain a development placeholder")
    (stage / "changelog.txt").write_text(changelog, encoding="utf-8")
    dist.mkdir(exist_ok=True)
    output = dist / f"{prefix}.zip"
    shutil.make_archive(str(output.with_suffix("")), "zip", stage.parent, prefix)
    print(f"archive={output}")


def upload(root: Path) -> None:
    token = os.environ.get("MOD_PORTAL_TOKEN")
    if not token:
        fail("mod_portal_token secret is required when upload_to_portal is true")
    info = read_json(root / "src" / "info.json")
    name, version = info.get("name"), info.get("version")
    archive = root / "dist" / f"{name}_{version}.zip"
    if not archive.is_file():
        fail(f"archive not found: {archive}")
    request = Request("https://mods.factorio.com/api/v2/mods/releases/init_upload", data=urlencode({"mod": name}).encode(), headers={"Authorization": f"Bearer {token}"})
    with urlopen(request) as response:
        upload_url = json.load(response)["upload_url"]
    boundary = "----factorio-devops-boundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{archive.name}\"\r\nContent-Type: application/zip\r\n\r\n").encode() + archive.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = Request(upload_url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urlopen(request) as response:
        payload = json.load(response)
    if not payload.get("success"):
        fail(f"portal upload failed: {payload}")


def start_development(root: Path) -> None:
    _, changelog_path, state_path = files(root)
    state = read_json(state_path)
    version_line = state.get("versionLine")
    if not isinstance(version_line, str) or not re.fullmatch(r"\d+\.\d+\.x", version_line):
        fail("release state must retain a numeric versionLine ending in .x")
    changelog = changelog_path.read_text(encoding="utf-8")
    if re.search(rf"(?m)^Version:\s*{re.escape(version_line)}\s*$", changelog):
        fail("changelog already contains a development placeholder")
    changelog_path.write_text(placeholder(version_line) + changelog, encoding="utf-8")
    state["versionState"] = "development"
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        fail("usage: factorio_mod_release.py {prepare|build|upload|start-development} ROOT [VERSION]")
    command, root = sys.argv[1], Path(sys.argv[2]).resolve()
    if command == "prepare" and len(sys.argv) == 4:
        prepare(root, sys.argv[3])
    elif command == "build" and len(sys.argv) == 4:
        build(root, sys.argv[3])
    elif command == "upload" and len(sys.argv) == 3:
        upload(root)
    elif command == "start-development" and len(sys.argv) == 3:
        start_development(root)
    else:
        fail("invalid command arguments")
