#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mss>=9.0.2", "pillow>=11.3.0"]
# ///
"""Record a README-sized demo GIF (or a single screenshot) with no system packages.

Recording a demo is the one launch task that needs a human: you have to hold the key and
speak. Everything around that is mechanical, so this script does all of it — region
selection, countdown, capture, resize, palette quantisation, frame dedupe, and a size
budget — leaving you with exactly two jobs: talk, then look at the GIF.

Deliberately dependency-light. `uv run scripts/record-demo.py` resolves `mss` and
`pillow` into uv's cache on first use; nothing is installed system-wide, no `sudo`, and
nothing is added to the project's own dependency tree.

    # pick a window by clicking it, 15 s, straight to the README's demo path
    uv run scripts/record-demo.py --window --seconds 15 --out docs/screenshots/demo.gif

    # a fixed region, useful for re-recording the identical shot
    uv run scripts/record-demo.py --region 100,100,960,540 --seconds 12

    # one still frame instead of a GIF
    uv run scripts/record-demo.py --window --shot --out docs/screenshots/tray-green.png

X11 only, which matches the machine this is recorded on. Under Wayland, `mss` cannot read
the screen; use `wf-recorder` + `gifski` and see docs/demo-guide.md.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

# A GIF wider than this is wasted bytes: GitHub renders README images at roughly this
# width, and every extra pixel is multiplied by the frame count.
DEFAULT_MAX_WIDTH = 900
# GitHub's hard ceiling for a file in a repo is far higher, but a demo that takes seconds
# to load has already lost the visitor it was meant to convert.
SIZE_BUDGET_MB = 5.0


def pick_window_region() -> tuple[int, int, int, int]:
    """Click a window; return its geometry. Uses xdotool, which is already installed."""
    if not shutil.which("xdotool"):
        sys.exit("xdotool not found — pass --region X,Y,W,H instead.")
    print("Click the window you want to record…", flush=True)
    win = subprocess.run(
        ["xdotool", "selectwindow"], capture_output=True, text=True, check=True
    ).stdout.strip()
    out = subprocess.run(
        ["xdotool", "getwindowgeometry", "--shell", win],
        capture_output=True, text=True, check=True,
    ).stdout
    g = dict(line.split("=", 1) for line in out.strip().splitlines())
    return int(g["X"]), int(g["Y"]), int(g["WIDTH"]), int(g["HEIGHT"])


def parse_region(spec: str) -> tuple[int, int, int, int]:
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("expected X,Y,WIDTH,HEIGHT")
    try:
        x, y, w, h = (int(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError("all four values must be integers") from None
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("width and height must be positive")
    return x, y, w, h


def countdown(seconds: int) -> None:
    for n in range(seconds, 0, -1):
        print(f"  {n}…", end="\r", flush=True)
        time.sleep(1)
    print("  RECORDING — go!    ", flush=True)


def capture(region, seconds: float, fps: int):
    """Grab frames for `seconds`, pacing to `fps`. Returns a list of PIL images."""
    import mss
    from PIL import Image

    x, y, w, h = region
    box = {"left": x, "top": y, "width": w, "height": h}
    interval = 1.0 / fps
    frames = []
    with mss.MSS() as sct:
        deadline = time.monotonic() + seconds
        next_at = time.monotonic()
        while time.monotonic() < deadline:
            raw = sct.grab(box)
            frames.append(Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX"))
            next_at += interval
            slack = next_at - time.monotonic()
            if slack > 0:
                time.sleep(slack)
            else:
                next_at = time.monotonic()  # dropped behind; don't accumulate debt
    return frames


def dedupe(frames, durations_ms: int):
    """Collapse runs of identical frames, extending the previous frame's duration instead.

    A dictation demo is mostly a still screen: you hold a key and wait for the transcript.
    Storing 40 identical frames of that wait is most of the file size for none of the
    information, so hold the frame and lengthen its duration instead.
    """
    kept, durations = [], []
    for frame in frames:
        if kept and frame.tobytes() == kept[-1].tobytes():
            durations[-1] += durations_ms
        else:
            kept.append(frame)
            durations.append(durations_ms)
    return kept, durations


def trim_still(frames, keep_head: int, keep_tail: int):
    """Drop the motionless run at each end, keeping a short beat of it.

    Lets you start a long recording and perform whenever you are ready, instead of racing a
    countdown — which matters most when the person recording and the person operating the
    keyboard are not the same. The dead air before you begin and after the text lands is
    removed, so the clip is as long as the action rather than as long as the session.

    Only *leading* and *trailing* stillness goes. A pause in the middle is content: it is
    the wait while speech is transcribed, which is exactly what a viewer needs to see.
    """
    if not frames:
        return frames
    sig = [f.tobytes() for f in frames]
    first, last = 0, len(frames) - 1
    while first < last and sig[first] == sig[first + 1]:
        first += 1
    while last > first and sig[last] == sig[last - 1]:
        last -= 1
    return frames[max(0, first - keep_head): min(len(frames), last + keep_tail + 1)]


def build_palette(frames, colors: int):
    """Derive one shared palette from the WHOLE recording, not from the first frame.

    Every frame must be quantised against the same palette or the colours shimmer between
    frames. The trap is where that palette comes from: a dictation demo opens on an empty
    editor, so frame 0 is the least colourful frame in the recording. A palette taken from
    it has almost no entries, every later frame quantises to a flat block, and the GIF
    writer then collapses those identical frames into a single-frame "animation".

    Sampling across the timeline instead means the palette covers the text that appears
    later, which is the entire point of the demo.
    """
    from PIL import Image

    step = max(1, len(frames) // 24)
    sample = frames[::step] or [frames[0]]
    w, h = sample[0].size
    strip = Image.new("RGB", (w, h * len(sample)))
    for i, frame in enumerate(sample):
        strip.paste(frame, (0, i * h))
    return strip.quantize(colors=colors, method=Image.MEDIANCUT)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--window", action="store_true", help="Click a window to record it.")
    src.add_argument("--region", type=parse_region, help="X,Y,WIDTH,HEIGHT.")
    src.add_argument(
        "--full", action="store_true",
        help="The whole primary screen. Frames are held in RAM until the end, so a "
             "full-screen capture costs roughly width×height×3 bytes per frame — prefer "
             "--window or --region for anything longer than a few seconds.",
    )
    ap.add_argument("--seconds", type=float, default=15.0, help="Recording length (15).")
    ap.add_argument("--fps", type=int, default=12, help="Frames per second (12).")
    ap.add_argument("--countdown", type=int, default=3, help="Seconds before capture (3).")
    ap.add_argument("--max-width", type=int, default=DEFAULT_MAX_WIDTH)
    ap.add_argument("--colors", type=int, default=128, help="Palette size (128).")
    ap.add_argument("--shot", action="store_true", help="One PNG instead of a GIF.")
    ap.add_argument(
        "--no-trim", action="store_true",
        help="Keep the motionless run at each end (trimming is on by default).",
    )
    ap.add_argument("--out", type=Path, default=Path("demo.gif"))
    args = ap.parse_args()

    if args.full:
        import mss
        with mss.MSS() as sct:
            m = sct.monitors[1]
            region = (m["left"], m["top"], m["width"], m["height"])
    elif args.window:
        region = pick_window_region()
    else:
        region = args.region
    print(f"Region: x={region[0]} y={region[1]} {region[2]}×{region[3]}")

    if args.shot:
        countdown(args.countdown)
        frame = capture(region, seconds=0.1, fps=1)[0]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        frame.save(args.out)
        print(f"Wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB)")
        return 0

    countdown(args.countdown)
    t0 = time.monotonic()
    frames = capture(region, args.seconds, args.fps)
    print(f"Captured {len(frames)} frames in {time.monotonic() - t0:.1f}s")
    if not frames:
        print("No frames captured.", file=sys.stderr)
        return 1

    if not args.no_trim:
        before = len(frames)
        frames = trim_still(frames, keep_head=args.fps // 2, keep_tail=args.fps)
        if len(frames) != before:
            print(
                f"Trimmed dead air: {before} → {len(frames)} frames "
                f"({len(frames) / args.fps:.1f}s of action)"
            )
        if not frames:
            print("Nothing moved during the recording.", file=sys.stderr)
            return 1

    if frames[0].width > args.max_width:
        scale = args.max_width / frames[0].width
        size = (args.max_width, int(frames[0].height * scale))
        from PIL import Image
        frames = [f.resize(size, Image.LANCZOS) for f in frames]
        print(f"Resized to {size[0]}×{size[1]}")

    kept, durations = dedupe(frames, durations_ms=int(1000 / args.fps))
    print(f"Deduped {len(frames)} → {len(kept)} frames")

    # One shared palette, sampled across the whole recording (see build_palette).
    from PIL import Image
    palette = build_palette(kept, args.colors)
    quantised = [f.quantize(palette=palette, dither=Image.FLOYDSTEINBERG) for f in kept]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    quantised[0].save(
        args.out,
        save_all=True,
        append_images=quantised[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    mb = args.out.stat().st_size / 1024 / 1024
    print(f"Wrote {args.out} ({mb:.2f} MB, {len(kept)} frames)")
    if mb > SIZE_BUDGET_MB:
        print(
            f"⚠ Over the {SIZE_BUDGET_MB} MB budget. Re-run with a tighter --region, "
            f"--fps 10, --colors 64, or a shorter --seconds.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
