#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# build-skill.sh — package each skill into an uploadable .zip for claude.ai.
#
# The zip must contain the skill folder itself at the top level:
#
#   knime-doc-generator.zip
#   └── knime-doc-generator/
#       ├── SKILL.md
#       ├── references/
#       └── scripts/
#
# Anthropic's own packager names the file <skill>.skill; that is the same zip
# under a different extension. .zip is used here because the people installing
# this skill are more likely to recognize it and less likely to have their
# browser or OS treat it as an unknown file type.
#
#   ./scripts/build-skill.sh            build every skill into dist/
#   ./scripts/build-skill.sh <name>     build just one
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/skills"
DIST_DIR="$REPO_ROOT/dist"

command -v zip >/dev/null 2>&1 || { echo "Error: 'zip' is required but not installed." >&2; exit 1; }

only="${1:-}"
mkdir -p "$DIST_DIR"
built=0

for skill_dir in "$SKILLS_DIR"/*/; do
  [ -d "$skill_dir" ] || continue
  name="$(basename "$skill_dir")"
  [ -z "$only" ] || [ "$only" = "$name" ] || continue

  if [ ! -f "$skill_dir/SKILL.md" ]; then
    echo "warning: skills/$name has no SKILL.md — skipping" >&2
    continue
  fi

  out="$DIST_DIR/$name.zip"
  rm -f "$out"

  # Zip from the skills/ directory so paths inside are "<name>/SKILL.md".
  # Excludes match Anthropic's packager: caches, bytecode and .DS_Store.
  ( cd "$SKILLS_DIR" && zip -q -r -X "$out" "$name" \
      -x '*/__pycache__/*' '*.pyc' '*/.DS_Store' '.DS_Store' \
         '*/.ruff_cache/*' '*/.pytest_cache/*' '*/.mypy_cache/*' )

  size="$(du -h "$out" | cut -f1 | tr -d ' ')"
  echo "built: dist/$name.zip ($size)"
  built=$((built + 1))
done

if [ "$built" -eq 0 ]; then
  if [ -n "$only" ]; then
    echo "Error: no skill named '$only' in skills/" >&2
  else
    echo "Error: no skills found in $SKILLS_DIR" >&2
  fi
  exit 1
fi

echo ""
echo "Upload a .zip at claude.ai -> Settings -> Capabilities -> Skills -> Upload skill."
