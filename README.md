# Face of Christ: one continuous spiral

A standalone reconstruction of Claude Mellan's 1649 engraving technique: a
portrait drawn as one continuous spiral line whose width follows the tones.

## Run

Use Python 3.10 or newer. From the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python mellan_spiral.py --svg --verify-raster
```

On Windows, activate with `.venv\Scripts\activate` instead. On first run
the script downloads the public-domain museum scan to
`assets/mellan_1649_met.jpg`; later runs work offline. Alternatively, place the
scan there yourself or pass any portrait with `--input`. No API key or
image-generation service is required.

## Resolution and continuity

The default PNG is **16,000 × 19,126 pixels**, with **210 continuous turns**.
The supplied render was checked across all **306,016,000 pixels**, using a
50% ink-coverage threshold. The result is **one connected ink component**
(8-neighbor connectivity) and **one connected paper component** (4-neighbor
connectivity). These checks detect broken strokes and paper islands caused
by neighboring turns touching. See [the render report](examples/render_report.json).

`--verify-raster` repeats these checks and returns a nonzero exit status on
failure. Raising the number of turns can require a higher raster resolution.

The SVG contains one ink path and no embedded portrait or image mask. Its
closed path is the outline of one open, continuously varying-width stroke.
Use the SVG to inspect the line at any zoom, or view the full PNG at native
resolution. Each run also writes a reduced `_preview.png` and a `_detail.png`.

The PNG is rendered in strips to keep memory bounded. Its lossless palette
preserves all 256 levels of antialiased ink coverage.

## Examples

```sh
# High-resolution PNG, SVG, and pixel connectivity check
python mellan_spiral.py --svg --verify-raster

# Fast preview
python mellan_spiral.py --width 3200 --output output/preview

# Larger print with verification
python mellan_spiral.py --width 24000 --svg --verify-raster --output output/large

# Another portrait; set the origin at its nose in image fractions
python mellan_spiral.py --input portrait.jpg --center 0.50 0.54 --svg --verify-raster

# Export the ordered centerline and width samples
python mellan_spiral.py --geometry --svg --verify-raster
```

`--width` accepts 400–32000 pixels. `--turns` controls spatial detail.
`--gamma` below 1 broadens shadows; above 1 opens them up. `--detail` adjusts
local contrast. `--descreen` controls suppression of old engraved lines in a
reference image. `--ink` and `--paper` accept six-digit hex colors.

Default outputs always go into the repository's `output/`, even when invoked
from another working directory. Existing outputs at the same prefix are
replaced. Lower-resolution previews may not preserve raster continuity.

## Method

1. Crop the museum scan to the portrait and veil, excluding the lower caption.
   Suppress its fine engraved pattern to recover the underlying tones.
2. Generate one open spiral starting at the nose. Inner turns are circular;
   the outer turns gradually approach the rounded rectangular veil.
3. Sample brightness along the line. Shadows broaden it; highlights narrow it.
   Correct widths for the perpendicular spacing between neighboring turns.
4. Keep widths positive, cap them at 88% of local spacing, and limit the
   offset at the tight central curl. Join both sides with rounded caps.
5. Render that same continuous ribbon to PNG and SVG.

This is a newly calculated engraving based on Mellan's portrait, rather than
an exact tracing of his hand-cut line. The reference supplies only the tones;
every mark in the output belongs to the computed spiral.

## Files

| Path | Purpose |
| --- | --- |
| `mellan_spiral.py` | Renderer, SVG export, and raster continuity checks |
| `requirements.txt` | Independent Python dependencies |
| `assets/mellan_1649_met.jpg` | Public-domain museum reference (downloaded on first run) |
| `examples/` | High-resolution render report |
| `output/` | Generated full PNG, SVG, previews, and report |

Full-resolution outputs can be recreated offline with the command above.

## Attribution

Claude Mellan (1598–1688), *Face of Christ on St. Veronica's Cloth*, 1649.
Engraving, second state of two. Metropolitan Museum of Art, accession
**69.581.5**. Purchase, The Elisha Whittelsey Collection, The Elisha Whittelsey
Fund, 1969. The museum marks the image **Public Domain**.

- [Museum record](https://www.metmuseum.org/art/collection/search/393752)
- [Original scan](https://images.metmuseum.org/CRDImages/dp/original/DP822671.jpg)
- [Technique reference](https://collections.hammer.ucla.edu/artwork/1962.33.1)

Source crop and nose coordinates are explicit in the code. The source hash
and render parameters are recorded in the JSON report.
