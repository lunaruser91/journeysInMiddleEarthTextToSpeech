#!/usr/bin/env python3
"""
probe_ocr.py — where the OCR time actually goes, on this machine.

Reported from a Windows laptop: 13 to 20 seconds per screen, against 0.35 s for
Apple Vision on a Mac. Tuning RapidOCR's detection size did not move it, so the
cause is something else and guessing has been tried.

This grabs one frame of whatever is on the display, crops it the way the narrator
does, and times the OCR under several configurations — thread counts, detection
sizes, and the recogniser alone. Run it with the game on screen, since a
dialogue box full of prose is the workload that matters.

    python probe_ocr.py

The numbers name the culprit. A time that falls with fewer threads is
contention. A time that falls with a smaller image is the detector. A time that
does not move is the machine, and then the answer is a different engine —
Windows has `Windows.Media.Ocr` built in, which this project does not wrap yet.
"""
from __future__ import annotations

import os
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import console  # noqa: E402

console.setup()

ROOT = Path(__file__).resolve().parent


def _frame():
    """One frame of the display, cropped as the narrator crops it."""
    import numpy as np  # noqa: F401

    from capture.base import open_display
    from ocr.base import crop
    from trigger import REGION

    cap = open_display(0)
    time.sleep(0.6)
    full = cap.grab()
    cap.close()
    if full is None:
        raise SystemExit("no frame arrived from the display")
    return full, crop(full, (0.0, REGION[0], 1.0, REGION[1]))


def _time(engine, box, runs: int = 3) -> tuple[float, int, str]:
    engine(box)                       # warm
    best, out = None, []
    for _ in range(runs):
        started = time.perf_counter()
        result, _ = engine(box)
        elapsed = time.perf_counter() - started
        if best is None or elapsed < best:
            best, out = elapsed, result or []
    return best, len(out), " ".join(x[1] for x in out)[:60]


def main() -> None:
    import yaml
    from rapidocr_onnxruntime import RapidOCR

    import rapidocr_onnxruntime as R

    full, box = _frame()
    print(f"display {full.shape[1]}x{full.shape[0]}  ->  crop "
          f"{box.shape[1]}x{box.shape[0]}")
    print(f"{platform.system()} {platform.machine()}  "
          f"{os.cpu_count()} logical cores\n")

    stock = yaml.safe_load(
        (Path(R.__file__).resolve().parent / "config.yaml").read_text("utf-8"))

    def build(**over):
        cfg = yaml.safe_load(yaml.safe_dump(stock))
        cfg["Global"]["use_angle_cls"] = over.pop("angle", True)
        for key in ("limit_type", "limit_side_len"):
            if key in over:
                cfg["Det"][key] = over.pop(key)
        for section in ("Det", "Cls", "Rec"):
            for key, value in over.items():
                cfg[section][key] = value
        tmp = ROOT / "output" / f".probe_{abs(hash(str(cfg)))}.yaml"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
        return RapidOCR(config_path=str(tmp)), tmp

    trials = [
        ("stock (min 736, angle on)", dict()),
        ("no angle classifier", dict(angle=False)),
        ("max 1280, no angle", dict(angle=False, limit_type="max",
                                    limit_side_len=1280)),
        ("max 960, no angle", dict(angle=False, limit_type="max",
                                   limit_side_len=960)),
        ("max 1280, 1 thread", dict(angle=False, limit_type="max",
                                    limit_side_len=1280,
                                    intra_op_num_threads=1)),
        ("max 1280, 2 threads", dict(angle=False, limit_type="max",
                                     limit_side_len=1280,
                                     intra_op_num_threads=2)),
        ("max 1280, 4 threads", dict(angle=False, limit_type="max",
                                     limit_side_len=1280,
                                     intra_op_num_threads=4)),
    ]

    print(f"{'configuration':30} {'best of 3':>10}  boxes  text")
    print("-" * 78)
    for label, over in trials:
        try:
            engine, tmp = build(**over)
            seconds, boxes, text = _time(engine, box)
            tmp.unlink(missing_ok=True)
            print(f"{label:30} {seconds:9.2f}s  {boxes:5}  {text}")
        except Exception as exc:  # noqa: BLE001
            print(f"{label:30} {'failed':>10}   {type(exc).__name__}: {exc}"[:110])

    print("\nA time that falls with fewer threads is contention.")
    print("A time that falls with a smaller image is the detector.")
    print("A time that does not move is the machine itself.")


if __name__ == "__main__":
    main()
