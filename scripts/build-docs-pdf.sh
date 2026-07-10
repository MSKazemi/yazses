#!/usr/bin/env bash
# Build the single master reference PDF for YazSes — "YazSes: The Complete
# Reference" — from the Markdown docs in docs/. Assembles architecture, the full
# feature reference, CLI reference, configuration, how-to guides, roadmap, and
# troubleshooting into one numbered, table-of-contents PDF.
#
# Toolchain (all user-space — no system install / no sudo):
#   * pandoc  — via the pip package `pypandoc-binary` (bundles the pandoc binary),
#               fetched ephemerally by `uv run --with`.
#   * xelatex — the system TeX Live engine (already present). Non-Latin glyphs in
#               feature examples (Arabic, Braille, symbols) get font fallback via
#               scripts/pdf-fallback.tex (ucharclasses). Colour emoji, which xelatex
#               cannot draw, is substituted to a short text label below.
#
# Usage:  bash scripts/build-docs-pdf.sh [output.pdf]
# Output: docs/yazses-complete-reference.pdf (gitignored; regenerate on demand).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCS="$ROOT/docs"
OUT="${1:-$DOCS/yazses-complete-reference.pdf}"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

echo "==> Regenerating reference docs (features / configuration / command-index)"
( cd "$ROOT" && uv run python scripts/gen-docs.py )

# Ordered table of contents for the master PDF. Each entry: "relative/path.md".
# Missing files are skipped with a warning (so the build still works mid-authoring).
DOC_ORDER=(
  "architecture.md"
  "features.md"
  "cli-reference.md"
  "command-index.md"
  "configuration.md"
  "how-to/index.md"
  "how-to/personal-vocabulary.md"
  "how-to/macros-and-snippets.md"
  "how-to/change-hotkey.md"
  "how-to/remote-dictation.md"
  "how-to/performance-tuning.md"
  "tutorials/transcribe-recordings.md"
  "roadmap.md"
  "troubleshooting.md"
  "install-linux.md"
  "macos-install.md"
  "windows-install.md"
  # NOTE: migration-v04-to-v10.md is intentionally excluded — it describes a
  # never-shipped Rust "v1.0" (Moonshine/Whisper.cpp/llama.cpp/Ollama/OpenAI,
  # cargo binaries) that does not match the real Python implementation. Left out
  # of the reference PDF until it is rewritten or removed.
  "privacy-statement.md"
)

COMBINED="$BUILD/combined.md"
: > "$COMBINED"

# strip a leading YAML front-matter block (--- ... ---) from a markdown file so
# pandoc doesn't render it as body text.
strip_frontmatter() {
  awk 'BEGIN{fm=0} NR==1 && $0=="---"{fm=1; next} fm==1 && $0=="---"{fm=0; next} fm==0{print}' "$1"
}

VERSION="$(cd "$ROOT" && uv run python -c 'from yazses import branding; print(branding.version())' 2>/dev/null || echo dev)"

for rel in "${DOC_ORDER[@]}"; do
  f="$DOCS/$rel"
  if [[ ! -f "$f" ]]; then
    echo "   (skip missing $rel)" >&2
    continue
  fi
  echo "   + $rel"
  # Each doc starts with a top-level `#` heading, which the `report` document
  # class renders as a chapter on a fresh page — so no explicit page break is
  # needed (and a literal \newpage would leak as text under the gfm reader).
  strip_frontmatter "$f" >> "$COMBINED"
  printf '\n\n' >> "$COMBINED"
done

# Colour emoji (e.g. 🤷) cannot be drawn by xelatex — substitute a short text
# label in the PDF source only (the Markdown docs keep the emoji, which renders on
# GitHub). Extend this list if new emoji enter the docs.
python3 - "$COMBINED" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
text = p.read_text(encoding="utf-8")
subs = {"🤷": "[shrug]"}
for emoji, label in subs.items():
    text = text.replace(emoji, label)
# Drop emoji-presentation variation selectors (U+FE0F) — zero-width, but xelatex
# warns and they follow symbols like ⚠️. The base glyph is kept.
text = text.replace("️", "")
p.write_text(text, encoding="utf-8")
PY

echo "==> Rendering PDF with pandoc + xelatex → $OUT"
cd "$ROOT"
uv run --with pypandoc-binary python - "$COMBINED" "$OUT" "$VERSION" "$ROOT/scripts/pdf-fallback.tex" "$ROOT/scripts/pandoc-tablewrap.lua" <<'PY'
import sys, pypandoc
combined, out, version, header, luafilter = sys.argv[1:6]
pypandoc.convert_file(
    combined, "pdf", outputfile=out, format="gfm",
    extra_args=[
        "--pdf-engine=xelatex",
        "-H", header,
        "--lua-filter", luafilter,      # wrap wide table cells (no overflow)
        "--toc", "--toc-depth=3",
        "-V", "toc-title=Contents",
        # NOTE: no --number-sections — several source docs (privacy, install)
        # carry their own manual section numbers and cross-references, which would
        # collide with auto-numbering ("19.14 13. ..."). ToC keeps page numbers +
        # hierarchy instead.
        "-V", "documentclass=report",
        "-V", "geometry:margin=2.2cm",
        "-V", "colorlinks=true", "-V", "linkcolor=RoyalBlue",
        "-V", "urlcolor=RoyalBlue", "-V", "toccolor=black",
        "-V", "mainfont=DejaVu Serif",
        "-V", "monofont=DejaVu Sans Mono",
        "-V", "sansfont=DejaVu Sans",
        "-M", "title=YazSes — The Complete Reference",
        "-M", f"subtitle=Local, offline voice dictation · v{version}",
        "-M", "author=Mohsen Seyedkazemi Ardebili",
    ],
)
print(f"Wrote {out}")
PY

if command -v pdfinfo >/dev/null 2>&1; then
  echo "==> $(pdfinfo "$OUT" | awk '/Pages/{print $2" pages"}')  $(du -h "$OUT" | cut -f1)"
else
  echo "==> Done: $OUT  ($(du -h "$OUT" | cut -f1))"
fi
