# Microsoft Store submission assets

The Store takes YazSes as an **unpackaged `.exe`** — you submit a link to the
installer, not a repackaged app. See `docs/code-signing.md` for the signing
requirement, which gates the whole submission.

## What the Store demands, and where it comes from

| Field | Required | Source |
|---|---|---|
| Screenshots (1 min, 4+ recommended) | **Yes** | `docs/screenshots/` — five are already ≥1366×768 |
| 1:1 box art | **Yes** | `boxart-1080.png` here |
| 2:3 poster art | Recommended | not made yet |
| Installer URL | **Yes** | the release asset, versioned and immutable |
| Installer parameters | **Yes** | `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` |

Usable screenshots today (checked, not assumed):

- `overlay-green-recording.jpg`, `overlay-purple-command-{1,2,3}.jpg` — 1400×1050
- `yazses-features.png` — 1844×1197

The tray shots are 212×73 and the `og-card` is 2:1, so neither qualifies.

## Regenerating the box art

`snap/gui/yazses.svg` already carries its own white rounded plate, so the square
is composited onto **white**, not onto the brand purple — purple leaves a thin
frame around the plate that reads as a mistake rather than a design.

```bash
uv run --group docs python - <<'PY'
import cairosvg, io
from PIL import Image
png = cairosvg.svg2png(url="snap/gui/yazses.svg", output_width=1080, output_height=1080)
fg = Image.open(io.BytesIO(png)).convert("RGBA")
bg = Image.new("RGBA", fg.size, (255, 255, 255, 255))
bg.alpha_composite(fg)
bg.convert("RGB").save("packaging/store/boxart-1080.png", "PNG", optimize=True)
PY
```

The transparent 512×512 `snap/gui/yazses.png` also satisfies the 1:1 requirement,
but transparent corners render unpredictably against light and dark Store chrome,
which is why an opaque version exists.
