# factorio-devops

Reusable GitHub Actions release workflow for Factorio 2.1 mods.

## Release contract

Each mod repository keeps mod files in `src/`, including `src/info.json`,
`src/changelog.txt`, and `src/thumbnail.png`. Its root contains `LICENSE`,
`COPYRIGHT`, `README.md`, `.factorio-release.json`, and the thin caller
workflow.

During development, `src/info.json` contains the next numeric patch version.
The current `src/changelog.txt` record uses that same version, such as `Version: 0.1.0`, with
`Date: TBD`; changes accumulate there. `.factorio-release.json` must be:

```json
{ "versionState": "development", "versionLine": "0.1.0" }
```

The release workflow finalizes that record, creates a release commit and
annotated `v<version>` tag, archives `src/` into
`<internal-name>_<version>.zip`, adds `LICENSE` and `COPYRIGHT`, creates af
draft GitHub release, uploads it to the Mod Portal,
publishes the GitHub release, and then increments `src/info.json` by one patch
and commits a fresh development record using that new version with `Date: TBD`.
For example, after releasing `1.1.0`, the next development commit begins at
`1.1.1` in both `info.json` and the changelog.

The caller's **release mode** controls the external publishing stages:

- **Commits Only** — create and push the release commit/tag, then create the
  next development commit. It does not build or publish an archive.
- **Commits and Release** — additionally create and publish the GitHub release.
- **Full** — also upload the ZIP to the Factorio Mod Portal.

## Installation

Put this repository at `kubiix/factorio-devops`. The template currently follows
its `main` branch; after creating and protecting a `v1` tag, replace the
workflow and tools references with `v1` to pin the shared automation version.
The shared repository needs to be public, or the caller needs a separate token
with read access to it for the tools checkout.
Create `FACTORIO_MOD_PORTAL_TOKEN` as an organization or repository Actions
secret. It must be an API key from the Factorio account that owns the mod or
has permission to release it, with **ModPortal: Publish Mods**, **Upload
Mods**, and **Edit Mods** enabled. The official API documents `Forbidden` for
insufficient permission, but does not spell out the Mod Portal's
owner/collaborator policy.

The **Full** release mode pulls the ZIP and metadata to the Mod Portal. If
`.factorio-release.json` has `"published": false` (or does not yet have the
field), it uses the two-stage Mod Publish API. Otherwise it uses the two-stage
release upload API. After the first successful publish, the following
development commit records `"published": true`.

The portal details are updated after either operation: `title` and `summary`
come from `src/info.json`; category, license, and tags come from
`modPortalContent/portalInfo.json`; and both `homepage` and `source_url` are
the current GitHub repository URL. A non-empty `description.md` overrides the
in-game description for the portal, while a non-empty `faq.md` supplies the
FAQ.

## Initialize a new mod

The mod template includes **Initialize own mod**, a one-use workflow for a fresh
repository. It only runs when the root `.factorio-release.json` has
`"versionState": "initPending"`; it also checks the public Mod Portal API and
fails when the requested internal name already exists. It sets `info.json`,
the development version line, the `origin` state, root `COPYRIGHT`, and
`modPortalContent` metadata. It leaves the template's MIT `LICENSE` unchanged,
then commits `Start development <initial_version>` and tags that commit as
`Init`. The optional `initial_version` input defaults to `0.1.0` when empty.
The release workflow copies those root legal files into the staged mod archive.

GitHub's manual Actions form supports single-choice inputs, but not a native
multi-select picker or Markdown editor. Categories are a picker; tags are a
validated comma-separated field; description and FAQ are string inputs saved
as Markdown files. `mod_title` becomes the Factorio `info.json` title, while
`display_name` becomes the Mod Portal title. The summary input updates the
in-game `info.json` description and `summary.txt`; the optional description
input updates only the future Mod Portal Markdown description. If it is empty,
the summary is used for `description.md`. `contact` and `homepage` are set to
the current GitHub repository URL.

Initialization does **not** publish the mod. Its first **Full** release uses
the Mod Publish API; later full releases upload only the new version.

## Mod Portal metadata

Keep portal-only assets outside `src/` so they are not shipped in the mod ZIP:

```text
modPortalContent/
  description.md
  summary.txt
  faq.md                 # optional
  portalInfo.json        # category, tags, license, homepage, source_url …
  screenshots/
```

`portalInfo.json` is used by the release workflow to update Mod Portal details.
Screenshots remain reserved for a later Mod Images API integration.

Example `portalInfo.json`:

```json
{
  "category": "utilities",
  "tags": ["logistics", "blueprints"],
  "license": "default_gnulgplv3"
}
```

Keep the Markdown in `description.md` and optional `faq.md` separate, and the
plain one-line portal summary in `summary.txt`. Future automation can read
these files directly and send the documented `edit_details` fields. Screenshot
uploads require the add → returned upload URL → edit ordering prescribed by
the Mod Images API.

## Safety notes

The GitHub release is created as a draft. A failed portal upload leaves the
tag and draft release for inspection and does not start the next development
cycle. Re-run only after resolving the error; this first version intentionally
does not attempt automatic recovery from a partially completed release.
