#!/usr/bin/env python3
"""Re-engrave Mellan's Face of Christ as one continuous, variable-width spiral.

Run:  python mellan_spiral.py
      python mellan_spiral.py --width 4800 --turns 230 --svg
      python mellan_spiral.py --input portrait.jpg --center 0.5 0.52 --svg

Dependencies: numpy, scipy, Pillow, matplotlib.  No API key is required.
The bundled public-domain museum photograph supplies ONLY the tonal reference.
Every ink mark in the output belongs to one newly computed spiral ribbon.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape
import zlib

import numpy as np
from PIL import Image, ImageOps
from scipy.ndimage import gaussian_filter, gaussian_filter1d, label, map_coordinates


HERE = Path(__file__).resolve().parent
SOURCE_URL = "https://images.metmuseum.org/CRDImages/dp/original/DP822671.jpg"
SOURCE_PAGE = "https://www.metmuseum.org/art/collection/search/393752"
SOURCE_FILE = HERE / "assets" / "mellan_1649_met.jpg"
# Mellan's own density; --spacing scales these defaults.
MELLAN_TURNS, MELLAN_MIN_WIDTH, MELLAN_MAX_WIDTH = 210, 0.055, 0.88
DEFAULT_SPACING = 2.0
# Pixels in the 2729 x 3645 museum image. Omit the separate lower inscription.
SOURCE_CROP = (52, 35, 2675, 3220)
SOURCE_NOSE = (1369.0, 1847.0)
INK = "#24231f"
PAPER = "#f5f0e4"


@dataclass
class Geometry:
    """One ordered open centerline and the width of its ink at each sample."""

    xy: np.ndarray
    normals: np.ndarray
    widths: np.ndarray
    theta: np.ndarray
    spacing: np.ndarray
    canvas: tuple[int, int]
    origin: tuple[float, float]


def obtain_reference() -> Path:
    """Use the offline asset, downloading it atomically only when absent."""
    if SOURCE_FILE.is_file():
        return SOURCE_FILE
    print("Downloading the public-domain Met reference...", flush=True)
    SOURCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SOURCE_FILE.with_suffix(".download")
    try:
        request = Request(SOURCE_URL, headers={"User-Agent": "MellanSpiral/1.0"})
        with urlopen(request, timeout=60) as response, temporary.open("wb") as out:
            while block := response.read(1024 * 1024):
                out.write(block)
        with Image.open(temporary) as check:
            check.verify()
        temporary.replace(SOURCE_FILE)
    except (OSError, URLError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"Could not fetch the reference. Save {SOURCE_URL} as {SOURCE_FILE}, "
            "or provide a local image with --input."
        ) from exc
    return SOURCE_FILE


def prepare_tone(args: argparse.Namespace) -> tuple[np.ndarray, tuple[float, float], Path]:
    """Recover continuous tones before sampling them; do not trace old lines."""
    historical = args.input is None
    source = obtain_reference() if historical else args.input.expanduser().resolve()
    with Image.open(source) as opened:
        rgba = ImageOps.exif_transpose(opened).convert("RGBA")
        white = Image.new("RGBA", rgba.size, "white")
        white.alpha_composite(rgba)
        image = white.convert("L")
    if historical:
        if image.size != (2729, 3645):
            raise ValueError("The museum asset has unexpected dimensions; use --input instead.")
        image = image.crop(SOURCE_CROP)
        x0, y0, x1, y1 = SOURCE_CROP
        default_center = ((SOURCE_NOSE[0] - x0) / (x1 - x0),
                          (SOURCE_NOSE[1] - y0) / (y1 - y0))
    else:
        default_center = (0.5, 0.5)

    # Work in reflected image brightness: ink coverage is an area mixture of
    # ink and paper. Linear-light photo conversion would over-darken this print.
    values = np.asarray(image, dtype=np.float64) / 255.0
    sigma = args.descreen if args.descreen is not None else (5.0 if historical else 0.6)
    if sigma > 0:
        values = gaussian_filter(values, sigma=sigma, mode="reflect")
    if historical:
        # Fixed levels preserve the artwork's intended tonal hierarchy.
        black, white_level = 0.28, 0.76
    else:
        black, white_level = np.percentile(values, [0.5, 99.5])
        if white_level - black < 1e-6:
            black, white_level = 0.0, 1.0
    values = np.clip((values - black) / (white_level - black), 0, 1)

    # Gentle broad local contrast restores form after descreening, without
    # reintroducing the narrow frequency band of the old engraved strokes.
    broad = gaussian_filter(values, sigma=max(2, image.width * 0.008), mode="reflect")
    values = np.clip(values + args.detail * (values - broad), 0, 1)
    return values, tuple(args.center or default_center), source


def spiral_geometry(tone: np.ndarray, center: tuple[float, float],
                    args: argparse.Namespace) -> Geometry:
    """Construct one spiral and calculate widths in its local normal direction.

    With t in [0, 2*pi*N], u=t/(2*pi*N), and angle a=t-pi/2:

        r(u,a) = R*u + (B(a)-R)*u**3
        p(t) = origin + r * (cos(a), sin(a))

    B is the radial boundary of an asymmetric superellipse. R is its minimum
    axial radius. The center starts circular and the outside gradually follows
    the rectangular veil. dr/du is positive, so successive turns stay ordered.
    No clipping, disconnected rings, lifted pen, or raster underlay is used.
    """
    width = args.width
    margin = width * 0.044
    inner_w = width - 2 * margin
    inner_h = inner_w * tone.shape[0] / tone.shape[1]
    height = round(inner_h + 2 * margin)
    inner_h = height - 2 * margin
    cx, cy = margin + center[0] * inner_w, margin + center[1] * inner_h
    left, right = cx - margin, width - margin - cx
    top, bottom = cy - margin, height - margin - cy
    base = min(left, right, top, bottom)
    end = 2 * math.pi * args.turns
    power = 8.0

    def evaluate(t: np.ndarray):
        a = t - math.pi / 2
        c, s = np.cos(a), np.sin(a)
        ax = np.where(c >= 0, right, left)
        ay = np.where(s >= 0, bottom, top)
        qx, qy = np.abs(c) / ax, np.abs(s) / ay
        den = qx**power + qy**power
        boundary = den ** (-1.0 / power)
        den_derivative = power * (
            -qx ** (power - 1) * np.sign(c) * s / ax
            + qy ** (power - 1) * np.sign(s) * c / ay
        )
        boundary_derivative = -boundary * den_derivative / (power * den)
        u = t / end
        radius = base * u + (boundary - base) * u**3
        dr = (base + 3 * (boundary - base) * u**2) / end + boundary_derivative * u**3
        xy = np.column_stack((cx + radius * c, cy + radius * s))
        tangent = np.column_stack((dr * c - radius * s, dr * s + radius * c))
        return xy, tangent, radius, boundary, u

    # Approximately equal arc-length samples keep fine modulation smooth and
    # avoid wasting millions of samples in the tiny innermost turns.
    coarse_t = np.linspace(0.0, end, args.turns * 720 + 1)
    coarse_xy = evaluate(coarse_t)[0]
    lengths = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(coarse_xy, axis=0), axis=1))]
    # Sampling is resolution independent: increasing --width increases output
    # resolution without changing the underlying artwork or vector geometry.
    step = width / 2600.0
    arc = np.linspace(0.0, lengths[-1], math.ceil(lengths[-1] / step) + 1)
    theta = np.interp(arc, lengths, coarse_t)
    # Arc-length sampling alone is too coarse for the tiny central curl.
    # An angular bound there preserves a smooth nib even under strong zoom.
    theta = np.unique(np.r_[theta, np.linspace(0, 4 * math.pi, 321)])
    xy, tangent, radius, boundary, u = evaluate(theta)
    speed = np.linalg.norm(tangent, axis=1)
    unit = tangent / speed[:, None]
    normals = np.column_stack((unit[:, 1], -unit[:, 0]))

    # The radial pitch is NOT the perpendicular gap on the squarer outer turns.
    # Correct for the normal projection, and use the smaller adjacent pitch.
    du = 1.0 / args.turns
    delta_out = base * du + (boundary - base) * ((u + du)**3 - u**3)
    delta_in = base * du + (boundary - base) * (u**3 - (u - du)**3)
    delta = np.where(u >= du, np.minimum(delta_in, delta_out), delta_out)
    projection = np.maximum(radius / speed, 0.20)
    spacing = delta * projection

    ix = (xy[:, 0] - margin) / inner_w * (tone.shape[1] - 1)
    iy = (xy[:, 1] - margin) / inner_h * (tone.shape[0] - 1)
    brightness = map_coordinates(tone, [iy, ix], order=1, mode="nearest", prefilter=False)
    darkness = np.clip(1.0 - brightness, 0, 1)**args.gamma
    coverage = args.min_width + (args.max_width - args.min_width) * darkness
    widths = spacing * coverage
    # Very light smoothing along the line avoids abrupt nib-width changes.
    widths = gaussian_filter1d(widths, sigma=0.8, mode="nearest")
    widths = np.minimum(widths, args.max_width * spacing)

    # Keep the offset ribbon regular at the tightly curved center. Without this
    # bound, a dark source pixel at the origin could produce a self-crossing nib.
    dunit = np.gradient(unit, theta, axis=0, edge_order=2)
    curvature = np.abs(unit[:, 0] * dunit[:, 1] - unit[:, 1] * dunit[:, 0]) / speed
    widths = np.minimum(widths, 1.2 / np.maximum(curvature, 1e-12))
    if not (np.isfinite(xy).all() and np.isfinite(widths).all() and (widths > 0).all()):
        raise ArithmeticError("The spiral contains invalid coordinates or a broken stroke.")
    return Geometry(xy, normals, widths, theta, spacing, (width, height), (cx, cy))


def ribbon_outline(geometry: Geometry) -> np.ndarray:
    """Walk one side, round the end, return along the other side, round the start."""
    p, n, half = geometry.xy, geometry.normals, geometry.widths * 0.5
    outer = p + n * half[:, None]
    inner = p - n * half[:, None]
    tangent = np.column_stack((-n[:, 1], n[:, 0]))
    a = np.linspace(0, math.pi, 13)[1:-1]
    end_cap = p[-1] + half[-1] * (
        np.cos(a)[:, None] * n[-1] + np.sin(a)[:, None] * tangent[-1])
    start_cap = p[0] + half[0] * (
        -np.cos(a)[:, None] * n[0] - np.sin(a)[:, None] * tangent[0])
    return np.concatenate((outer, end_cap, inner[::-1], start_cap, outer[:1]))


class ComponentCounter:
    """Count connected components across raster strips with union-find.

    Foreground uses 8-neighbor connectivity; background uses the dual
    4-neighbor connectivity. One component of each means connected ink with no
    enclosed paper islands caused by adjacent turns touching.
    """

    def __init__(self, width: int, diagonal: bool):
        self.previous = np.zeros(width, dtype=np.int64)
        self.parents = [0]
        self.count = 0
        self.pixels = 0
        self.diagonal = diagonal

    def root(self, index: int) -> int:
        while self.parents[index] != index:
            self.parents[index] = self.parents[self.parents[index]]
            index = self.parents[index]
        return index

    def consume(self, mask: np.ndarray) -> None:
        structure = np.ones((3, 3), dtype=bool) if self.diagonal else np.array(
            [[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
        labels, number = label(mask, structure=structure)
        self.pixels += int(np.count_nonzero(mask))
        offset = len(self.parents) - 1
        self.parents.extend(range(offset + 1, offset + number + 1))
        self.count += number
        first = labels[0].astype(np.int64)
        first[first > 0] += offset
        neighbors = [(self.previous, first)]
        if self.diagonal:
            neighbors += [(self.previous[:-1], first[1:]),
                          (self.previous[1:], first[:-1])]
        for above, below in neighbors:
            connected = (above > 0) & (below > 0)
            pairs = np.unique(np.column_stack((above[connected], below[connected])), axis=0)
            for a, b in pairs:
                ra, rb = self.root(int(a)), self.root(int(b))
                if ra != rb:
                    self.parents[rb] = ra
                    self.count -= 1
        self.previous = labels[-1].astype(np.int64)
        self.previous[self.previous > 0] += offset


def png_chunk(stream, kind: bytes, payload: bytes) -> None:
    stream.write(struct.pack(">I", len(payload)))
    stream.write(kind)
    stream.write(payload)
    stream.write(struct.pack(">I", zlib.crc32(payload, zlib.crc32(kind)) & 0xffffffff))


def render_png(outline: np.ndarray, canvas: tuple[int, int], destination: Path,
               ink: str, paper: str, scale: float = 1.0,
               window: tuple[float, float, float, float] | None = None,
               verify: bool = False) -> dict | None:
    """Rasterize in bounded-memory strips, preserving 256 coverage levels.

    Indexed PNG is lossless here: every pixel is the same ink/paper mixture,
    and its palette index is the 8-bit antialiased coverage. It avoids a
    multi-gigabyte RGB allocation for print-resolution renders.
    """
    from matplotlib.backends.backend_agg import RendererAgg
    from matplotlib.colors import to_rgba
    from matplotlib.path import Path as MplPath
    from matplotlib.transforms import Affine2D

    if window is None:
        x0, y0, w, h = 0.0, 0.0, float(canvas[0]), float(canvas[1])
    else:
        x0, y0, w, h = window
    rw, rh = round(w * scale), round(h * scale)
    codes = np.full(len(outline), MplPath.LINETO, dtype=np.uint8)
    codes[0], codes[-1] = MplPath.MOVETO, MplPath.CLOSEPOLY
    path = MplPath(outline, codes)
    path.should_simplify = False
    ink_rgb = np.array([int(ink[i:i+2], 16) for i in (1, 3, 5)], dtype=np.int32)
    paper_rgb = np.array([int(paper[i:i+2], 16) for i in (1, 3, 5)], dtype=np.int32)
    coverage = np.arange(256, dtype=np.int32)[:, None]
    palette = ((coverage * ink_rgb + (255 - coverage) * paper_rgb + 127) // 255).astype(np.uint8)
    foreground = ComponentCounter(rw, diagonal=True) if verify else None
    background = ComponentCounter(rw, diagonal=False) if verify else None
    previous_row = np.zeros(rw, dtype=np.uint8)
    strip_height = max(16, min(512, 4_000_000 // rw))
    compressor = zlib.compressobj(level=6)
    with destination.open("wb") as out:
        out.write(b"\x89PNG\r\n\x1a\n")
        png_chunk(out, b"IHDR", struct.pack(">IIBBBBB", rw, rh, 8, 3, 0, 0, 0))
        png_chunk(out, b"PLTE", palette.tobytes())
        png_chunk(out, b"pHYs", struct.pack(">IIB", 11811, 11811, 1))
        for top in range(0, rh, strip_height):
            band_h = min(strip_height, rh - top)
            renderer = RendererAgg(rw, band_h, 72)
            gc = renderer.new_gc()
            gc.set_linewidth(0)
            gc.set_antialiased(True)
            # Positive image y points downward; Agg y points upward. Each strip
            # uses the same global pixel grid, preventing seams at its edges.
            transform = (Affine2D().translate(-x0, -y0).scale(scale, -scale)
                         .translate(0, band_h + top))
            renderer.draw_path(gc, path, transform, rgbFace=to_rgba(ink))
            gc.restore()
            alpha = np.asarray(renderer.buffer_rgba())[:, :, 3]
            if foreground is not None and background is not None:
                foreground.consume(alpha >= 128)
                background.consume(alpha < 128)
            # PNG's Up filter; uint8 subtraction deliberately wraps modulo 256.
            filtered = np.empty((band_h, rw + 1), dtype=np.uint8)
            filtered[:, 0] = 2
            filtered[0, 1:] = alpha[0] - previous_row
            filtered[1:, 1:] = alpha[1:] - alpha[:-1]
            previous_row = alpha[-1].copy()
            compressed = compressor.compress(filtered.tobytes())
            if compressed:
                png_chunk(out, b"IDAT", compressed)
            if verify and top // strip_height % 16 == 0:
                print(f"  Rasterized and checked {top + band_h:,} / {rh:,} rows", flush=True)
        tail = compressor.flush()
        if tail:
            png_chunk(out, b"IDAT", tail)
        png_chunk(out, b"IEND", b"")
    if foreground is not None and background is not None:
        return {"coverage_threshold": "128/255", "ink_connectivity": 8,
                "paper_connectivity": 4, "ink_components": foreground.count,
                "paper_components": background.count, "ink_pixels": foreground.pixels,
                "passed": foreground.count == 1 and background.count == 1}
    return None


def write_svg(outline: np.ndarray, geometry: Geometry, path: Path,
              ink: str, paper: str) -> None:
    """SVG has no variable-width stroke primitive: use ONE filled stroke outline."""
    width, height = geometry.canvas
    with path.open("w", encoding="utf-8", newline="\n") as out:
        out.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                  f'viewBox="0 0 {width} {height}">\n')
        out.write('<title>Face of Christ — one continuous spiral, after Claude Mellan</title>\n')
        out.write('<desc>A newly calculated variable-width spiral beginning at the nose. '
                  'The single closed path is the boundary of that open ink stroke. '
                  'There are no embedded images, masks, or separate facial strokes.</desc>\n')
        out.write(f'<rect width="{width}" height="{height}" fill="{escape(paper)}"/>\n')
        out.write(f'<path id="spiral-ink" fill="{escape(ink)}" stroke="none" d="')
        out.write(f'M{outline[0, 0]:.3f},{outline[0, 1]:.3f}')
        for start in range(1, len(outline) - 1, 8192):
            chunk = outline[start:min(start + 8192, len(outline) - 1)]
            out.write("".join(f'L{x:.3f},{y:.3f}' for x, y in chunk))
        out.write('Z"/>\n</svg>\n')


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, help="any image to draw; default: the Mellan reference")
    p.add_argument("--output", type=Path, default=HERE / "output" / "face_of_christ", help="output filename prefix (default: beside this script)")
    p.add_argument("--width", type=int, default=16000, help="PNG width in pixels (default: 16000)")
    p.add_argument("--spacing", type=float, default=DEFAULT_SPACING,
                   help=f"line spacing relative to Mellan's density; larger is sparser, 1 is his 210 turns (default: {DEFAULT_SPACING:g})")
    p.add_argument("--turns", type=int, help="spiral revolutions (default: 210 / spacing)")
    p.add_argument("--center", type=float, nargs=2, metavar=("X", "Y"), help="origin in source fractions, e.g. 0.50 0.55")
    p.add_argument("--gamma", type=float, default=0.95, help="darkness exponent; smaller makes broader shadows")
    p.add_argument("--detail", type=float, default=0.20, help="broad local contrast, from 0 to 1")
    p.add_argument("--descreen", type=float, help="Gaussian sigma in source pixels; default: 5 for Mellan, 0.6 for photos")
    p.add_argument("--min-width", type=float, help="minimum ink width as a fraction of turn spacing (default: 0.055 / sqrt(spacing))")
    p.add_argument("--max-width", type=float, help="maximum ink width as a fraction of turn spacing (default: 0.88 / sqrt(spacing))")
    p.add_argument("--ink", default=INK, help="six-digit ink color, e.g. '#24231f'")
    p.add_argument("--paper", default=PAPER, help="six-digit paper color")
    p.add_argument("--svg", action="store_true", help="also save the single-ribbon vector artwork")
    p.add_argument("--geometry", action="store_true", help="save ordered centerline coordinates and widths in NPZ")
    p.add_argument("--verify-raster", action="store_true", help="check that the full PNG has one ink component and one paper component")
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if not math.isfinite(args.spacing) or not 0.5 <= args.spacing <= 10:
        p.error("--spacing must be between 0.5 and 10")
    # Wider spacing means fewer turns, each narrower relative to its gap, so
    # paper opens up between lines while strokes stay about as bold as before.
    thinning = math.sqrt(args.spacing)
    if args.turns is None:
        args.turns = max(10, round(MELLAN_TURNS / args.spacing))
    if args.min_width is None:
        args.min_width = MELLAN_MIN_WIDTH / thinning
    if args.max_width is None:
        args.max_width = min(0.90, MELLAN_MAX_WIDTH / thinning)
    if not 400 <= args.width <= 32000:
        p.error("--width must be between 400 and 32000")
    if not 10 <= args.turns <= 600:
        p.error("--turns must be between 10 and 600")
    if not 0 < args.min_width < args.max_width <= 0.90:
        p.error("require 0 < --min-width < --max-width <= 0.90")
    if not math.isfinite(args.gamma) or not 0.1 <= args.gamma <= 5:
        p.error("--gamma must be between 0.1 and 5")
    if not math.isfinite(args.detail) or not 0 <= args.detail <= 1:
        p.error("--detail must be between 0 and 1")
    if args.descreen is not None and (not math.isfinite(args.descreen) or args.descreen < 0):
        p.error("--descreen must be a finite nonnegative number")
    if args.center and not all(math.isfinite(v) and 0.1 <= v <= 0.9 for v in args.center):
        p.error("--center coordinates must be between 0.1 and 0.9")
    for color in (args.ink, args.paper):
        if len(color) != 7 or color[0] != "#" or any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
            p.error("--ink and --paper must be six-digit hex colors, such as '#24231f'")

    prefix = args.output.expanduser().resolve()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    output = lambda suffix: prefix.parent / (prefix.name + suffix)
    started = time.perf_counter()
    print("Recovering tonal detail...", flush=True)
    tone, center, source = prepare_tone(args)
    print(f"Constructing one spiral with {args.turns} revolutions...", flush=True)
    geometry = spiral_geometry(tone, center, args)
    outline = ribbon_outline(geometry)
    print(f"Rendering {len(geometry.xy):,} centerline samples...", flush=True)
    raster_check = render_png(outline, geometry.canvas, output(".png"), args.ink, args.paper,
                              verify=args.verify_raster)
    render_png(outline, geometry.canvas, output("_preview.png"), args.ink, args.paper,
               scale=1400 / geometry.canvas[1])
    # A fresh vector rasterization of the nose, rather than enlarged PNG pixels.
    zoom_width = args.width * 0.17
    cx, cy = geometry.origin
    render_png(outline, geometry.canvas, output("_detail.png"), args.ink, args.paper,
               scale=1400 / zoom_width,
               window=(cx - zoom_width / 2, cy - zoom_width / 2, zoom_width, zoom_width))
    if args.svg:
        print("Writing single-ribbon SVG...", flush=True)
        write_svg(outline, geometry, output(".svg"), args.ink, args.paper)
    if args.geometry:
        np.savez_compressed(output("_geometry.npz"), xy=geometry.xy, widths=geometry.widths,
                            theta=geometry.theta, canvas=geometry.canvas, origin=geometry.origin)
    report = {
        "title": "Face of Christ — a computational engraving after Claude Mellan",
        "source": SOURCE_PAGE if args.input is None else source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "reference_is_embedded_in_output": False,
        "canvas_pixels": list(geometry.canvas),
        "centerline_subpaths": 1,
        "spiral_turns": args.turns,
        "centerline_samples": len(geometry.xy),
        "stroke_width_range_pixels": [float(geometry.widths.min()), float(geometry.widths.max())],
        "maximum_width_over_local_spacing": float(np.max(geometry.widths / geometry.spacing)),
        "origin_pixels": list(geometry.origin),
        "source_center_fractions": list(center),
        "all_widths_strictly_positive": bool((geometry.widths > 0).all()),
        "raster_validation": raster_check,
        "parameters": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    output("_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {output('.png')} ({geometry.canvas[0]} x {geometry.canvas[1]})")
    print(f"Finished in {report['elapsed_seconds']:.1f} seconds.")
    if raster_check is not None and not raster_check["passed"]:
        print("Raster continuity check failed: increase --width. "
              "See the report for component counts.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
