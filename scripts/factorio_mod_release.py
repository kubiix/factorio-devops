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

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
CHANGELOG_CATEGORIES = {"Changes", "Info", "Major Features", "Features", "Optimizations", "Bugfixes"}


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
    return f"""Version: {version_line}
Date: TBD
  Changes:
    -
---------------------------------------------------------------------------------------------------
"""


def placeholder_block(text: str, version_line: str) -> tuple[int, int]:
    marker = "---------------------------------------------------------------------------------------------------"
    end = text.find(marker)
    if end < 0:
        fail("top changelog record must end with a separator")
    record = text[:end]
    lines = record.splitlines()
    if not lines or lines[0] != f"Version: {version_line}":
        fail(f"top changelog record must contain 'Version: {version_line}'")
    if len(lines) < 2 or lines[1] != "Date: TBD":
        fail("development changelog record must contain 'Date: TBD'")
    category: str | None = None
    entry_count = 0
    for line in lines[2:]:
        if not line:
            continue
        category_match = re.fullmatch(r"  (.+):", line)
        if category_match:
            if category is not None and entry_count == 0:
                fail(f"changelog category '{category}' must contain at least one non-empty item")
            category = category_match.group(1)
            if category not in CHANGELOG_CATEGORIES:
                fail(f"unsupported changelog category '{category}'")
            entry_count = 0
        elif re.fullmatch(r"    - \S.*", line):
            if category is None:
                fail("changelog item must follow a category")
            entry_count += 1
        elif line == "    -":
            fail("changelog item must not be empty")
        elif re.fullmatch(r"      \S.*", line):
            if category is None or entry_count == 0:
                fail("changelog continuation must follow a non-empty item")
        else:
            fail(f"invalid changelog line: {line!r}")
    if category is None:
        fail("development changelog record must contain at least one category")
    if entry_count == 0:
        fail(f"changelog category '{category}' must contain at least one non-empty item")
    return 0, end


def prepare(root: Path, version: str) -> None:
    info_path, changelog_path, state_path = files(root)
    info, state = read_json(info_path), read_json(state_path)
    version_line = state.get("versionLine")
    if state.get("versionState") != "development" or not isinstance(version_line, str) or not VERSION_RE.fullmatch(version_line):
        fail(".factorio-release.json must mark development and contain a numeric versionLine")
    old = info.get("version")
    if not isinstance(old, str) or version_tuple(version) < version_tuple(old):
        fail("release version must be greater or equal than src/info.json version")
    if version_tuple(version) < version_tuple(version_line):
        fail("release version must be greater or equal than the development changelog version")
    changelog = changelog_path.read_text(encoding="utf-8")
    start, end = placeholder_block(changelog, version_line)
    record = changelog[start:end]
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    record = re.sub(rf"(?m)^Version:\s*{re.escape(version_line)}\s*$", f"Version: {version}", record, count=1)
    record = re.sub(r"(?m)^Date:\s*TBD\s*$", f"Date: {date}", record, count=1)
    # The tagged commit contains only published records.  The following commit
    # restores the development placeholder after the external uploads succeed.
    changelog_path.write_text(record + changelog[end:], encoding="utf-8")
    info["version"] = version
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    state["versionState"] = "release"
    state["versionLine"] = version
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    notes = record.strip() + "\n"
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
    (stage / "changelog.txt").write_text(changelog, encoding="utf-8")
    dist.mkdir(exist_ok=True)
    output = dist / f"{prefix}.zip"
    shutil.make_archive(str(output.with_suffix("")), "zip", stage.parent, prefix)
    print(f"archive={output}")


def portal_token() -> str:
    token = os.environ.get("MOD_PORTAL_TOKEN")
    if not token:
        fail("mod_portal_token secret is required for Mod Portal publishing")
    return token


def multipart(fields: list[tuple[str, str]], archive: Path | None = None) -> tuple[bytes, str]:
    boundary = "----factorio-devops-boundary"
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    if archive:
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{archive.name}\"\r\nContent-Type: application/zip\r\n\r\n".encode())
        body.extend(archive.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def portal_request(url: str, fields: list[tuple[str, str]], token: str | None = None, archive: Path | None = None) -> dict:
    if archive:
        body, content_type = multipart(fields, archive)
    else:
        body, content_type = multipart(fields)
    headers = {"Content-Type": content_type}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, data=body, headers=headers)) as response:
        payload = json.load(response)
    if not payload.get("success", "upload_url" in payload):
        fail(f"Mod Portal request failed: {payload}")
    return payload


def archive_for_info(root: Path, info: dict) -> Path:
    name, version = info.get("name"), info.get("version")
    archive = root / "dist" / f"{name}_{version}.zip"
    if not archive.is_file():
        fail(f"archive not found: {archive}")
    if not isinstance(name, str) or not name or not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        fail("src/info.json must contain a valid name and numeric version")
    return archive


def upload_version(root: Path) -> None:
    info = read_json(root / "src" / "info.json")
    archive = archive_for_info(root, info)
    name = info["name"]
    token = portal_token()
    upload_url = portal_request("https://mods.factorio.com/api/v2/mods/releases/init_upload", [("mod", name)], token)["upload_url"]
    portal_request(upload_url, [], archive=archive)


def publish(root: Path) -> None:
    info = read_json(root / "src" / "info.json")
    archive = archive_for_info(root, info)
    name = info["name"]
    token = portal_token()
    upload_url = portal_request("https://mods.factorio.com/api/v2/mods/init_publish", [("mod", name)], token)["upload_url"]
    portal_request(upload_url, [], archive=archive)


def text_if_present(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def edit_details(root: Path) -> None:
    info = read_json(root / "src" / "info.json")
    portal = read_json(root / "modPortalContent" / "portalInfo.json")
    name, title, summary = info.get("name"), info.get("title"), info.get("description")
    category, license_name, tags = portal.get("category"), portal.get("license"), portal.get("tags", [])
    if not all(isinstance(value, str) and value for value in (name, title, summary, category, license_name)):
        fail("info.json and portalInfo.json must contain non-empty name, title, description, category, and license")
    if not isinstance(tags, list) or not all(isinstance(tag, str) and tag for tag in tags):
        fail("modPortalContent/portalInfo.json tags must be an array of non-empty strings")
    repository_url = os.environ.get("REPOSITORY_URL", "").strip()
    if not re.fullmatch(r"https?://[^\s]+", repository_url):
        fail("REPOSITORY_URL must be the current http(s) repository URL")
    description = text_if_present(root / "modPortalContent" / "description.md") or summary
    fields = [("mod", name), ("title", title), ("summary", summary), ("description", description), ("category", category), ("license", license_name), ("homepage", repository_url), ("source_url", repository_url)]
    fields.extend(("tags", tag) for tag in tags)
    faq = text_if_present(root / "modPortalContent" / "faq.md")
    if faq:
        fields.append(("faq", faq))
    portal_request("https://mods.factorio.com/api/v2/mods/edit_details", fields, portal_token())


def pull(root: Path) -> bool:
    state = read_json(root / ".factorio-release.json")
    published = state.get("published") is True
    if published:
        upload_version(root)
    else:
        publish(root)
    edit_details(root)
    return not published


def start_development(root: Path, published: bool = False) -> None:
    info_path, changelog_path, state_path = files(root)
    info = read_json(info_path)
    state = read_json(state_path)
    release_version = state.get("versionLine")
    if state.get("versionState") != "release" or not isinstance(release_version, str) or not VERSION_RE.fullmatch(release_version):
        fail("release state must retain the numeric release version in versionLine")
    current_version = info.get("version")
    if not isinstance(current_version, str):
        fail("src/info.json must contain a numeric release version")
    major, minor, patch = version_tuple(current_version)
    next_version = f"{major}.{minor}.{patch + 1}"
    changelog = changelog_path.read_text(encoding="utf-8")
    if re.search(rf"(?m)^Version:\s*{re.escape(next_version)}\s*$", changelog):
        fail("changelog already contains a development placeholder")
    changelog_path.write_text(placeholder(next_version) + changelog, encoding="utf-8")
    info["version"] = next_version
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    state["versionState"] = "development"
    state["versionLine"] = next_version
    if published:
        state["published"] = True
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        fail("usage: factorio_mod_release.py {prepare|build|publish|upload-version|edit-details|pull|start-development} ROOT [VERSION|--published]")
    command, root = sys.argv[1], Path(sys.argv[2]).resolve()
    if command == "prepare" and len(sys.argv) == 4:
        prepare(root, sys.argv[3])
    elif command == "build" and len(sys.argv) == 4:
        build(root, sys.argv[3])
    elif command == "publish" and len(sys.argv) == 3:
        publish(root)
    elif command == "upload-version" and len(sys.argv) == 3:
        upload_version(root)
    elif command == "edit-details" and len(sys.argv) == 3:
        edit_details(root)
    elif command == "pull" and len(sys.argv) == 3:
        print(str(pull(root)).lower())
    elif command == "start-development" and len(sys.argv) in (3, 4):
        if len(sys.argv) == 4 and sys.argv[3] != "--published":
            fail("start-development accepts only --published")
        start_development(root, len(sys.argv) == 4)
    else:
        fail("invalid command arguments")
