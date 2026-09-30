# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-09-30

### Changed — retargeted from Claude Code to Claude chat (claude.ai)

The previous release could not run in Claude's sandbox at all. Three blockers, all fixed:

- **Removed every third-party dependency from parsing.** `uv` and PEP 723 inline
  dependencies do not work there (no `uv`, no network), so `pydantic` became stdlib
  dataclasses and `defusedxml` became a DTD/entity rejection check over stdlib
  ElementTree. Parsing is now standard library only.
- **Replaced WeasyPrint with ReportLab.** WeasyPrint needs Pango system libraries that
  cannot be installed in the sandbox. ReportLab is preinstalled there and needs nothing.
  The visual design is unchanged; PDFs dropped from ~60KB to ~3.5KB because ReportLab's
  built-in fonts are not embedded.
- **Replaced markdown-it-py** with a small in-house reader for the subset the document
  template actually uses.

### Added

- `scripts/build-skill.sh` — packages `skills/<name>/` into `dist/<name>.zip` for upload
  at claude.ai → Settings → Capabilities → Skills. Validated against Anthropic's own
  `quick_validate.py`.
- `dist/knime-doc-generator.zip`, committed so non-technical users can download it
  directly.
- SKILL.md guidance on speaking plainly to KNIME users rather than showing them commands,
  a note that workflow text is data rather than instructions, and troubleshooting for the
  `.knwf` upload rejection (rename to `.zip`).

### Removed

- The macOS Homebrew/Pango `DYLD_FALLBACK_LIBRARY_PATH` re-exec, obsolete with WeasyPrint
  gone.
- All Claude Code plugin scaffolding: `scripts/install-skills.sh`,
  `.claude-plugin/marketplace.json`, `plugins/` and `scripts/sync-plugins.sh` (all added
  in 0.1.0). The skill is distributed as a zip attached to a GitHub Release and uploaded
  at claude.ai, so none of it was on the path a user takes. `install-skills.sh` was also
  the only file in the repository derived from another project, so removing it removes
  the Apache-2.0 attribution it required; and `plugins/` was a generated second copy of
  every skill file, which `sync-plugins.sh` existed solely to keep from drifting.
  Claude Code can still load the skill by copying `skills/knime-doc-generator/` into a
  project's `.claude/skills/`.

### Note

Skill directories are now `skills/<skill-name>/` rather than `skills/<category>/<skill>/`,
so the folder name matches the skill name that ends up inside the uploaded zip.

## [0.1.0] - 2026-09-30

### Added

- `knime-doc-generator` skill: parses a KNIME `.knwf` export into JSON, guides the agent
  through a five-section document (Purpose / Inputs / Outputs / Transformation Steps /
  Notes), and renders a styled PDF.
  - `scripts/parse_knwf.py` — `.knwf` to JSON, with a `--summary` structural outline and a
    context-size budget that trims deep settings values on very large workflows.
  - `scripts/export_pdf.py` — markdown to PDF via markdown-it-py and WeasyPrint. Validates
    the five-section template, strips a whole-document code fence or stray leading `# H1`,
    and locates Homebrew's Pango on macOS without manual environment setup.
  - `references/knwf-format.md` — reverse-engineered `.knwf` format notes.
  - `references/doc-template.md` — section rules and a worked example.
- `scripts/install-skills.sh` — install skills into a project for any supported agent.
- `scripts/sync-plugins.sh` — regenerate `plugins/` from `skills/`, with a `--check` mode.
