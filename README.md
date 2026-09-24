# Mellan line drawing

Turns any image into a single continuous spiral line whose width follows the
tones, after Claude Mellan's 1649 engraving *Face of Christ on St. Veronica's
Cloth*. Point it at your own photo with `--input`. With no input, it redraws
Mellan's engraving itself.

## Run

Use Python 3.10 or newer. From the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python mellan_spiral.py --input photo.jpg --output output/photo --svg --verify-raster
```

On Windows, activate with `.venv\Scripts\activate` instead. On first run
the script downloads the public-domain museum scan to
`assets/mellan_1649_met.jpg`; later runs work offline. Alternatively, place the
scan there yourself or pass any portrait with `--input`. No API key or
image-generation service is required.

## Using your own image

`--input` accepts any image Pillow can open (JPEG, PNG, TIFF, WebP, …), in
color or grayscale. It is converted to grayscale, EXIF rotation is honoured,
and transparent areas are treated as white paper. Tones are auto-levelled
between the 0.5th and 99.5th brightness percentiles, so no pre-editing is
needed.

- **Spiral origin.** The spiral starts at the image centre by default. For a
  portrait, place it on the nose or another focal point with `--center X Y`,
  in fractions of the image width and height (each 0.1–0.9, measured from the
  top left).
- **Framing.** The whole image is drawn; crop it beforehand to frame the
  subject. The output follows the input's proportions.
- **Output name.** Outputs default to `output/face_of_christ*`, so pass
  `--output` to keep renders of different images apart.
- **Tuning.** Low-contrast photos benefit from a higher `--detail`. Raise
  `--descreen` to smooth away halftone dots, film grain, or engraved hatching
  in scans.

## Line spacing

`--spacing` sets how open the drawing is. It is measured against Mellan's own
density: `--spacing 1` is his 210 turns, the default `2` is a sparser 105
turns, and `4` gives 52 widely spaced turns. Larger values draw fewer turns
with more paper between them. Line widths scale with the square root of the
spacing, so each line gets somewhat bolder while the gaps between them grow
faster. Smaller values, down to `0.5`, are denser than Mellan's print and may
need a larger `--width` to stay continuous.

```sh
python mellan_spiral.py --input photo.jpg --spacing 1   # dense, like Mellan's print
python mellan_spiral.py --input photo.jpg --spacing 3   # open and graphic
```

`--spacing` only sets defaults. An explicit `--turns`, `--min-width` or
`--max-width` overrides the value it would derive: 210 / spacing turns, and
0.055 / √spacing and 0.88 / √spacing of the local gap.


## Resolution and continuity

The default PNG is 16,000 pixels wide, and its height follows the image
(19,126 pixels for the Mellan scan). The included render was made at Mellan's
own density (`--spacing 1`, **210 continuous turns**) and was checked across all **306,016,000 pixels**, using a
50% ink-coverage threshold. The result is **one connected ink component**
(8-neighbor connectivity) and **one connected paper component** (4-neighbor
connectivity). These checks detect broken strokes and paper islands caused
by neighboring turns touching. See [the render report](examples/render_report.json).

`--verify-raster` repeats these checks and returns a nonzero exit status on
failure. The default `--spacing 2` and sparser settings passed the same
check at 16,000 pixels in testing. Denser settings can require a higher
raster resolution.

The SVG contains one ink path and no embedded portrait or image mask. Its
closed path is the outline of one open, continuously varying-width stroke.
Use the SVG to inspect the line at any zoom, or view the full PNG at native
resolution. Each run also writes a reduced `_preview.png` and a `_detail.png`.

The PNG is rendered in strips to keep memory bounded. Its lossless palette
preserves all 256 levels of antialiased ink coverage.

## Examples

```sh
# Your photo, spiral starting at the nose
python mellan_spiral.py --input portrait.jpg --center 0.50 0.54 --output output/portrait --svg

# Sparser, bolder lines
python mellan_spiral.py --input portrait.jpg --spacing 3 --output output/portrait_open

# Fast preview of your photo
python mellan_spiral.py --input portrait.jpg --width 3200 --output output/portrait_preview

# Mellan's own engraving at his original density, with connectivity check
python mellan_spiral.py --spacing 1 --svg --verify-raster

# Larger print with verification
python mellan_spiral.py --width 24000 --svg --verify-raster --output output/large

# Export the ordered centerline and width samples
python mellan_spiral.py --geometry --svg --verify-raster
```

`--width` accepts 400–32000 pixels. `--spacing` (0.5–10) sets line density;
`--turns`, `--min-width` and `--max-width` fine-tune it.
`--gamma` below 1 broadens shadows; above 1 opens them up. `--detail` adjusts
local contrast. `--descreen` sets the blur in source pixels used to suppress
fine texture (default 0.6 for your images, 5 for the Mellan scan). `--ink` and `--paper` accept six-digit hex colors.

Default outputs always go into the repository's `output/`, even when invoked
from another working directory. Existing outputs at the same prefix are
replaced. Lower-resolution previews may not preserve raster continuity.

## Method

1. Load the image as grayscale and lightly blur it to recover the underlying
   tones. For the default Mellan scan, crop to the portrait and veil and blur
   more strongly to suppress his engraved line pattern.
2. Generate one open spiral starting at the origin. Inner turns are circular;
   the outer turns gradually approach the rounded rectangular frame.
3. Sample brightness along the line. Shadows broaden it; highlights narrow it.
   Correct widths for the perpendicular spacing between neighboring turns.
4. Keep widths positive, cap them at `--max-width` of local spacing, and limit the
   offset at the tight central curl. Join both sides with rounded caps.
5. Render that same continuous ribbon to PNG and SVG.

The input image supplies only the tones; every mark in the output belongs to
the computed spiral. Rendered from Mellan's print, the result is a newly
calculated engraving, not a tracing of his hand-cut line.

## Files

| Path | Purpose |
| --- | --- |
| `mellan_spiral.py` | Renderer, SVG export, and raster continuity checks |
| `requirements.txt` | Independent Python dependencies |
| `assets/mellan_1649_met.jpg` | Default Mellan reference (downloaded on first run without `--input`) |
| `examples/` | High-resolution render report |
| `output/` | Generated full PNG, SVG, previews, and report |

## Attribution

The default reference is Claude Mellan (1598–1688), *Face of Christ on St. Veronica's Cloth*, 1649.
Engraving, second state of two. Metropolitan Museum of Art, accession
**69.581.5**. Purchase, The Elisha Whittelsey Collection, The Elisha Whittelsey
Fund, 1969. The museum marks the image **Public Domain**.

- [Museum record](https://www.metmuseum.org/art/collection/search/393752)
- [Original scan](https://images.metmuseum.org/CRDImages/dp/original/DP822671.jpg)
- [Technique reference](https://collections.hammer.ucla.edu/artwork/1962.33.1)

Source crop and nose coordinates are explicit in the code. The source hash
and render parameters are recorded in the JSON report.
