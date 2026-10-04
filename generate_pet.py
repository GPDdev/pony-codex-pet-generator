"""Offline Pony Town GIF to native Codex v1 pet converter (Python 3.10+)."""
import argparse
from bisect import bisect_right
from collections import defaultdict
import html
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from PIL import Image, ImageOps

VERSION = "0.1.0"
CELL = (192, 208)
ATLAS = (1536, 1872)
# Native v1 row order and playback timing, checked against the desktop client.
TIMINGS = {
    "idle": [1680, 660, 660, 840, 840, 1920],
    "running-right": [120] * 7 + [220],
    "running-left": [120] * 7 + [220],
    "waving": [140] * 3 + [280],
    "jumping": [140] * 4 + [280],
    "failed": [140] * 7 + [240],
    "waiting": [150] * 5 + [260],
    "running": [120] * 5 + [220],
    "review": [150] * 5 + [280],
}
ACTIONS = {
    "idle": ("stand",),
    "running-right": ("fly", "trot", "stand"),
    "running-left": ("fly", "trot", "stand"),
    "waving": ("applause", "laugh", "stand"),
    "jumping": ("dance move 1", "trot", "stand"),
    "failed": ("yawn", "lie", "stand"),
    "waiting": ("boop", "stand"),
    "running": ("dance-4", "trot", "stand"),
    "review": ("sit", "lie", "stand"),
}
KNOWN = set(TIMINGS) | {action for actions in ACTIONS.values() for action in actions}


def action_name(path):
    """Recognize bare names and Pony Town's character/action/export suffixes."""
    name = path.stem.lower().replace("_", " ")
    while re.search(r"-(blinking|padded|\d+x)$", name):
        name = re.sub(r"-(blinking|padded|\d+x)$", "", name)
    return next((a for a in sorted(KNOWN, key=len, reverse=True)
                 if name == a or name.endswith("-" + a)), None)


def discover(source):
    source = Path(source).resolve()
    if not source.is_dir():
        raise ValueError("GIF folder does not exist.")
    files = sorted(p for p in source.iterdir() if p.suffix.lower() == ".gif")
    if not files:
        raise ValueError("No GIF files found (search is not recursive).")
    by_action = defaultdict(list)
    for path in files:
        action = action_name(path)
        if action:
            by_action[action].append(path)
    return source, files, by_action


def resolve_rows(source, mapping=None):
    source, files, by_action = discover(source)
    if mapping is None:
        mapping = {}
    if not isinstance(mapping, dict) or set(mapping) - set(TIMINGS):
        raise ValueError("Mapping must be an object keyed by the nine supported states.")
    rows, warnings = [], []
    for state in TIMINGS:
        spec = mapping.get(state)
        if spec is not None:
            if not isinstance(spec, dict) or set(spec) - {"file", "frames", "mirror"}:
                raise ValueError(f"{state}: expected file/frames/mirror fields.")
            filename = spec.get("file")
            if not isinstance(filename, str) or not filename:
                raise ValueError(f"{state}: file must be a GIF filename.")
            path = (source / filename).resolve()
            if path.parent != source or path.suffix.lower() != ".gif" or not path.is_file():
                raise ValueError(f"{state}: select a GIF directly inside the source folder.")
        else:
            candidates = (state,) + ACTIONS[state]
            action = next((a for a in candidates if by_action[a]), None)
            if action is None:
                raise ValueError(f"{state}: no suitable GIF. Supply stand.gif or an explicit mapping.")
            if len(by_action[action]) != 1:
                raise ValueError(f"Multiple '{action}' GIFs: keep one character per folder or use --mapping.")
            path = by_action[action][0]
            if action not in (state, ACTIONS[state][0]):
                warnings.append(f"{state}: fallback to {action}.")
            spec = {}
        mirror = spec.get("mirror", state == "running-left")
        if not isinstance(mirror, bool):
            raise ValueError(f"{state}: mirror must be true or false.")
        rows.append((state, path, spec.get("frames"), mirror))
    unused = sorted(p.name for p in files if p not in {r[1] for r in rows})
    if unused:
        warnings.append("Unused GIFs: " + ", ".join(unused))
    return rows, warnings


def load_gif(path):
    frames, durations, boxes = [], [], []
    with Image.open(path) as gif:
        if gif.format != "GIF" or max(gif.size) > 2048 or gif.n_frames > 1000:
            raise ValueError(f"{path.name}: invalid GIF or exceeds 2048px / 1000-frame limit.")
        if gif.width * gif.height * gif.n_frames > 100_000_000:
            raise ValueError(f"{path.name}: decoded GIF exceeds 100 million pixels.")
        for index in range(gif.n_frames):
            gif.seek(index)
            frame = gif.convert("RGBA").copy()
            alpha = frame.getchannel("A")
            if alpha.getextrema()[0] == 255:
                raise ValueError(f"{path.name}: opaque background; export a transparent GIF first.")
            bbox = alpha.getbbox()
            if bbox:
                boxes.append(bbox)
            frames.append(frame)
            durations.append(max(10, int(gif.info.get("duration", 100))))
    if not boxes:
        raise ValueError(f"{path.name}: completely transparent GIF.")
    bounds = (min(b[0] for b in boxes), min(b[1] for b in boxes),
              max(b[2] for b in boxes), max(b[3] for b in boxes))
    return frames, durations, bounds


def sample_frames(state, frames, durations):
    if state == "idle":
        # ponytail: duration-based blink heuristic, use explicit frames for unusual stand GIFs.
        totals = defaultdict(int)
        for frame, duration in zip(frames, durations):
            totals[frame.tobytes()] += duration
        standing = max(totals, key=totals.get)
        stand = next(i for i, f in enumerate(frames) if f.tobytes() == standing)
        alternatives = [i for i, f in enumerate(frames) if f.tobytes() != standing
                        and f.getchannel("A").getbbox()]
        shortest = min((durations[i] for i in alternatives), default=0)
        brief = [i for i in alternatives if durations[i] == shortest]
        blink = brief[len(brief) // 2] if brief else stand
        return [stand, blink, stand, stand, stand, stand]
    cumulative, elapsed = [], 0
    for duration in durations:
        elapsed += duration
        cumulative.append(elapsed)
    native = TIMINGS[state]
    starts, elapsed_native = [], 0
    for duration in native:
        starts.append(min(len(frames) - 1, bisect_right(cumulative,
                      elapsed_native / sum(native) * elapsed)))
        elapsed_native += duration
    return starts


def validate_atlas(path):
    with Image.open(path) as image:
        if image.format != "WEBP" or image.size != ATLAS or image.mode != "RGBA":
            raise ValueError("Invalid v1 atlas format, dimensions or alpha mode.")
        for row, (state, timing) in enumerate(TIMINGS.items()):
            for column in range(8):
                cell = image.crop((column * 192, row * 208, (column + 1) * 192, (row + 1) * 208))
                bbox = cell.getchannel("A").getbbox()
                if column < len(timing):
                    if not bbox or bbox[0] < 8 or bbox[1] < 8 or bbox[2] > 184 or bbox[3] > 200:
                        raise ValueError(f"{state} cell {column}: empty or clipped.")
                elif bbox:
                    raise ValueError(f"{state}: unused cells must be transparent.")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Atlas exceeds 20 MiB.")


def write_package(root, rows, loaded, name, pet_id, description, scale, facing, warnings):
    atlas = Image.new("RGBA", ATLAS)
    report = {"generatorVersion": VERSION, "format": "v1", "scale": scale,
              "sourceFacing": facing, "warnings": warnings, "rows": []}
    preview = root / "previews"
    preview.mkdir()
    for row, (state, path, indices, mirror) in enumerate(rows):
        frames, durations, bounds = loaded[path]
        if indices is None:
            indices = sample_frames(state, frames, durations)
        if (not isinstance(indices, list) or len(indices) != len(TIMINGS[state])
                or any(type(i) is not int or not 0 <= i < len(frames) for i in indices)):
            raise ValueError(f"{state}: frames needs {len(TIMINGS[state])} valid zero-based frame indices.")
        size = (max(1, round((bounds[2] - bounds[0]) * scale)),
                max(1, round((bounds[3] - bounds[1]) * scale)))
        cells = []
        for column, index in enumerate(indices):
            sprite = frames[index].crop(bounds).resize(size, Image.Resampling.NEAREST)
            cell = Image.new("RGBA", CELL)
            cell.alpha_composite(sprite, ((192 - size[0]) // 2, 196 - size[1]))
            if mirror != (facing == "left"):
                cell = ImageOps.mirror(cell)
            atlas.alpha_composite(cell, (column * 192, row * 208))
            cells.append(cell)
        if len({c.tobytes() for c in cells}) == 1:
            warnings.append(f"{state}: sampled cells are static; choose frame indices if needed.")
        cells[0].save(preview / f"{state}.gif", save_all=True, append_images=cells[1:],
                      duration=TIMINGS[state], loop=0, disposal=2, optimize=False)
        report["rows"].append({"state": state, "file": path.name, "frames": indices,
                               "mirror": mirror, "size": list(size), "sourceBounds": bounds})
    # Remove invisible RGB residue, so the exported sheet has clean transparent padding.
    clean = Image.new("RGBA", ATLAS)
    clean.alpha_composite(atlas)
    clean.save(root / "spritesheet.webp", lossless=True, exact=True)
    validate_atlas(root / "spritesheet.webp")
    manifest = {"id": pet_id, "displayName": name, "description": description,
                "spriteVersionNumber": 1, "spritesheetPath": "spritesheet.webp"}
    (root / "pet.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clean.save(root / "contact-sheet.png")
    cards = "".join(f'<figure><img src="previews/{s}.gif" alt="{s}"><figcaption>{s}</figcaption></figure>'
                    for s in TIMINGS)
    (root / "preview.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        f'<title>{html.escape(name)} — Pet preview</title><style>body{{background:#202a3c;color:#fff;'
        'font:16px system-ui;padding:24px}main{display:flex;flex-wrap:wrap}figure{margin:12px;'
        'text-align:center;background:#34445d;border-radius:16px;padding:12px}img{width:192px;'
        'height:208px;image-rendering:pixelated}</style>'
        f'<h1>{html.escape(name)}</h1><p>Animation preview only; app interactions are controlled by the desktop client.</p>'
        f'<main>{cards}</main></html>', encoding="utf-8")
    with zipfile.ZipFile(root / f"{pet_id}.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for file in ("pet.json", "spritesheet.webp"):
            archive.write(root / file, f"{pet_id}/{file}")
    return report


def generate(source, output, name="My Pony", pet_id="my-pony", description="Pony Town companion",
             mapping=None, scale=None, facing="right"):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", pet_id) or len(pet_id) > 80:
        raise ValueError("Pet ID: 1–80 lowercase letters, digits and single hyphens.")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError("Name must contain 1–100 characters.")
    if not isinstance(description, str) or len(description) > 1000:
        raise ValueError("Description must contain at most 1000 characters.")
    if facing not in ("left", "right"):
        raise ValueError("Source facing must be left or right.")
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Output already exists. Choose a new folder; nothing was overwritten.")
    rows, warnings = resolve_rows(source, mapping)
    loaded = {path: load_gif(path) for path in dict.fromkeys(r[1] for r in rows)}
    widths = [b[2] - b[0] for _, _, b in loaded.values()]
    heights = [b[3] - b[1] for _, _, b in loaded.values()]
    fit = min(1.0, 176 / max(widths), 184 / max(heights))
    if scale is None:
        scale = fit
    if not isinstance(scale, (int, float)) or not math.isfinite(scale) or not 0 < scale <= fit:
        raise ValueError(f"Scale must be positive and at most {fit:.6f} to avoid clipping.")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Build in a temporary sibling: failed conversions never leave half a pet behind.
    with tempfile.TemporaryDirectory(prefix="pony-pet-", dir=output.parent) as temp:
        staged = Path(temp) / "package"
        staged.mkdir()
        report = write_package(staged, rows, loaded, name, pet_id, description, scale, facing, warnings)
        if output.exists():
            raise ValueError("Output appeared during conversion; refusing to overwrite it.")
        shutil.move(str(staged), str(output))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", help="Folder containing one character's transparent GIFs")
    parser.add_argument("--output", default="output/my-pony", help="New output folder (never overwritten)")
    parser.add_argument("--name", default="My Pony")
    parser.add_argument("--id", default="my-pony", dest="pet_id")
    parser.add_argument("--description", default="Pony Town companion")
    parser.add_argument("--mapping", type=Path, help="JSON state → file/frames/mirror overrides")
    parser.add_argument("--scale", type=float, help="Shared nearest-neighbor scale; default: fit without enlarging")
    parser.add_argument("--facing", choices=("left", "right"), default="right", help="Direction the source GIFs face")
    parser.add_argument("--gui", action="store_true", help="Open the local graphical interface")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    if args.gui:
        try:
            from gui import launch
        except ImportError as error:
            parser.exit(1, f"GUI unavailable: {error}. Install Python with tkinter or use the CLI.\n")
        from tkinter import TclError
        try:
            launch()
        except TclError as error:
            parser.exit(1, f"GUI unavailable: {error}. Use an official Python installation with Tcl/Tk, or use the CLI.\n")
        return
    if not args.source:
        parser.error("provide a source folder or --gui")
    try:
        mapping = json.loads(args.mapping.read_text(encoding="utf-8-sig")) if args.mapping else None
        report = generate(args.source, args.output, args.name, args.pet_id, args.description,
                          mapping, args.scale, args.facing)
    except (ValueError, OSError, Image.DecompressionBombError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"Created {Path(args.output).resolve()}")
    for warning in report["warnings"]:
        print(f"Warning: {warning}")


if __name__ == "__main__":
    main()
