"""Offline regression tests; synthetic sprites avoid redistributing Pony Town art."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image, ImageDraw, ImageOps
import generate_pet as pet


def gif(path, dimensions=(80, 100), opaque=False):
    frames = []
    for shift in (0, 2, 5):
        frame = Image.new("RGBA", dimensions, (20, 20, 20, 255) if opaque else (0, 0, 0, 0))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((15, 20 - shift, 42, 75 - shift), fill=(75, 165, 225, 255))
        draw.rectangle((30, 27 - shift, 33, 29 - shift), fill=(255, 255, 255, 255))
        frames.append(frame)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=[1000, 50, 80],
                   loop=0, disposal=2, optimize=False)


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "input"
        self.source.mkdir()
        for action in {a[0] for a in pet.ACTIONS.values()}:
            gif(self.source / f"pony-town-Example-{action}-blinking-padded-4x.gif")

    def tearDown(self):
        self.temp.cleanup()

    def test_end_to_end_and_directions(self):
        output = self.root / "pet"
        report = pet.generate(self.source, output, name="天蓝 <pony>", pet_id="test-pony")
        self.assertEqual(len(report["rows"]), 9)
        self.assertEqual(sum(len(r["frames"]) for r in report["rows"]), 57)
        self.assertEqual(report["scale"], 1)
        self.assertEqual(report["rows"][0]["frames"], [0, 1, 0, 0, 0, 0])
        self.assertNotIn(str(self.source), (output / "report.json").read_text(encoding="utf-8"))
        self.assertIn("天蓝 &lt;pony&gt;", (output / "preview.html").read_text(encoding="utf-8"))
        manifest = json.loads((output / "pet.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["spriteVersionNumber"], 1)
        pet.validate_atlas(output / "spritesheet.webp")
        with Image.open(output / "spritesheet.webp") as atlas:
            for column in range(8):
                right = atlas.crop((column * 192, 208, (column + 1) * 192, 416))
                left = atlas.crop((column * 192, 416, (column + 1) * 192, 624))
                self.assertEqual(ImageOps.mirror(right).tobytes(), left.tobytes())
        for state, durations in pet.TIMINGS.items():
            with Image.open(output / "previews" / f"{state}.gif") as preview:
                total = 0
                for index in range(preview.n_frames):
                    preview.seek(index)
                    total += preview.info["duration"]
                self.assertEqual(total, sum(durations))
        with zipfile.ZipFile(output / "test-pony.zip") as archive:
            self.assertEqual(set(archive.namelist()), {"test-pony/pet.json", "test-pony/spritesheet.webp"})
            self.assertEqual(archive.read("test-pony/spritesheet.webp"), (output / "spritesheet.webp").read_bytes())

    def test_source_left_reverses_all_rows(self):
        pet.generate(self.source, self.root / "r")
        pet.generate(self.source, self.root / "l", facing="left")
        with Image.open(self.root / "r/spritesheet.webp") as right, Image.open(self.root / "l/spritesheet.webp") as left:
            for row, durations in enumerate(pet.TIMINGS.values()):
                for col in range(len(durations)):
                    box = (col * 192, row * 208, (col + 1) * 192, (row + 1) * 208)
                    self.assertEqual(ImageOps.mirror(right.crop(box)).tobytes(), left.crop(box).tobytes())

    def test_never_overwrite_and_failed_output_cleanup(self):
        output = self.root / "existing"
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already exists"):
            pet.generate(self.source, output)
        self.assertEqual(marker.read_text(), "keep")
        bad_map = {"idle": {"file": "pony-town-Example-stand-blinking-padded-4x.gif", "frames": [999] * 6}}
        with self.assertRaisesRegex(ValueError, "valid zero-based"):
            pet.generate(self.source, self.root / "failed", mapping=bad_map)
        self.assertFalse((self.root / "failed").exists())
        self.assertFalse(list(self.root.glob("pony-pet-*")))

    def test_reject_bad_inputs(self):
        for bad_id in ("../outside", "A pony", "a--b", ""):
            with self.subTest(bad_id=bad_id), self.assertRaises(ValueError):
                pet.generate(self.source, self.root / "unused", pet_id=bad_id)
        for scale in (0, float("nan"), float("inf"), 100):
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                pet.generate(self.source, self.root / "unused", scale=scale)
        with self.assertRaisesRegex(ValueError, "inside"):
            pet.generate(self.source, self.root / "unused", mapping={"idle": {"file": "../outside.gif"}})
        with self.assertRaisesRegex(ValueError, "nine"):
            pet.generate(self.source, self.root / "unused", mapping={"unknown": {}})
        opaque = self.root / "opaque.gif"
        gif(opaque, opaque=True)
        with self.assertRaisesRegex(ValueError, "opaque"):
            pet.load_gif(opaque)
        blank = self.root / "blank.gif"
        Image.new("RGBA", (20, 20)).save(blank)
        with self.assertRaisesRegex(ValueError, "completely transparent"):
            pet.load_gif(blank)

    def test_ambiguous_exports_require_mapping(self):
        gif(self.source / "pony-town-Another-stand-blinking-padded-4x.gif")
        with self.assertRaisesRegex(ValueError, "Multiple"):
            pet.resolve_rows(self.source)
        rows, _ = pet.resolve_rows(self.source, {"idle": {"file": "pony-town-Example-stand-blinking-padded-4x.gif"}})
        self.assertEqual(len(rows), 9)

    def test_shared_scale_and_fallback(self):
        folder = self.root / "single"
        folder.mkdir()
        gif(folder / "stand.gif")
        report = pet.generate(folder, self.root / "fallback", scale=0.5)
        self.assertTrue(any("fallback" in warning for warning in report["warnings"]))
        self.assertTrue(all(r["size"] == [14, 30] for r in report["rows"]))
        self.assertEqual(pet.action_name(Path("pony-town-Name With Spaces-dance-4-padded-2x.gif")), "dance-4")

    def test_cli_help_and_conversion(self):
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            pet.main([str(self.source), "--output", str(self.root / "cli"), "--name", "CLI"])
        self.assertIn("Created", stream.getvalue())
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit_info:
            pet.main(["--help"])
        self.assertEqual(exit_info.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
