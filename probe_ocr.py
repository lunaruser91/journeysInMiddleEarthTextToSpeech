#!/usr/bin/env python3
"""
probe_ocr.py — where the OCR time actually goes, on this machine.

Reported from a Windows laptop: 13 to 20 seconds per screen, against 0.35 s for
Apple Vision on a Mac. This grabs one frame of whatever is on the display, crops
it the way the narrator does, and times the OCR under several configurations.
Run it with the game on screen, since a dialogue box full of prose is the
workload that matters.

    python probe_ocr.py

It takes minutes rather than seconds, and most of that is the first two rows:
they are the slow settings, timed four times each. That is not a hang.

## Why this file was rewritten

The first version timed seven configurations by writing yaml files and handing
them to `RapidOCR(config_path=...)`. There is no `config_path` parameter
(rapid_ocr_api.py:22 hardcodes the path); it lands in `**kwargs` and is filed
under Global as a key nothing reads. So all seven rows measured the stock
settings, printed identical text, and moved only with the leftover thread pools
of the engines the probe never released. Read by its own rule — "a time that
does not move is the machine" — it pointed at the machine, and the machine was
innocent.

So every row here prints **the shape actually handed to each network**, and the
milliseconds spent inside it. A configuration that does not arrive now shows up
as an unchanged tensor, not as a slow computer. The two are only
distinguishable if you look.

Fidelity is printed beside the time for the same reason: speed bought by reading
less is not speed. And the machine's own load is printed first, because this one
was 91% busy before the OCR started and that doubles every number below.
"""
from __future__ import annotations

import ctypes
import gc
import os
import platform
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import console  # noqa: E402

console.setup()


def _cpu_times() -> tuple[int, int]:
    """(idle, total) in 100 ns ticks, or (0, 0) where that cannot be asked."""
    if platform.system() != "Windows":
        return 0, 0
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return 0, 0

    def whole(ft):
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

    # kernel time already includes idle time, so total is kernel + user.
    return whole(idle), whole(kernel) + whole(user)


def _busy(before: tuple[int, int], after: tuple[int, int]) -> float | None:
    idle, total = after[0] - before[0], after[1] - before[1]
    return None if total <= 0 else 100.0 * (1.0 - idle / total)


def _frame():
    """One frame of the display, cropped as the narrator crops it."""
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


def main() -> None:
    from rapidocr_onnxruntime import RapidOCR, utils

    full, box = _frame()

    # Every call any network receives, with its real input shape. This is the
    # part the old probe lacked, and the only thing that tells a setting which
    # did not arrive from a machine which is slow.
    calls: list[tuple[tuple[int, ...], float]] = []
    stock_call = utils.OrtInferSession.__call__

    def watching(self, content):
        started = time.perf_counter()
        out = stock_call(self, content)
        calls.append((tuple(content.shape), time.perf_counter() - started))
        return out

    utils.OrtInferSession.__call__ = watching

    idle_before = _cpu_times()
    time.sleep(1.0)
    ambient = _busy(idle_before, _cpu_times())

    print(f"display {full.shape[1]}x{full.shape[0]}  ->  crop "
          f"{box.shape[1]}x{box.shape[0]}")
    # The load line is a separate print, not a conditional inside the machine
    # line: `_busy` returns None off Windows, and folding the two together threw
    # away the core count on every platform that cannot answer.
    print(f"{platform.system()} {platform.machine()}  {os.cpu_count()} logical "
          f"cores")
    if ambient is not None:
        print(f"machine {ambient:.0f}% busy in the second before the probe "
              f"starts")
        if ambient > 50:
            print("     (that is high. Every time below is partly the queue, "
                  "not the work.)")
    print()

    # `det_model_path` and `rec_model_path` are not decoration: update_det_params
    # reads det_dict['model_path'] unconditionally (utils.py:251), so any det_*
    # without it raises KeyError. None means "keep the packaged model".
    det = dict(det_model_path=None, det_limit_type="max")
    rec = dict(rec_model_path=None)
    trials = [
        ("as shipped", dict()),
        ("no angle classifier", dict(use_angle_cls=False)),
        ("+ longest side 1280", dict(use_angle_cls=False, **det,
                                     det_limit_side_len=1280)),
        ("+ longest side 960", dict(use_angle_cls=False, **det,
                                    det_limit_side_len=960)),
        ("+ one crop per rec batch", dict(use_angle_cls=False, **det, **rec,
                                          det_limit_side_len=960,
                                          rec_batch_num=1)),
        ("longest side 1280, rec batch 1", dict(use_angle_cls=False, **det,
                                                **rec, det_limit_side_len=1280,
                                                rec_batch_num=1)),
    ]

    reference = None
    print(f"{'configuration':32} {'best of 3':>10} {'fidelity':>9}  shapes fed "
          f"to the networks")
    print("-" * 100)
    for label, kwargs in trials:
        try:
            engine = RapidOCR(**kwargs)
            engine(box)                               # warm
            best, text, shapes = None, "", []
            for _ in range(3):
                calls.clear()
                started = time.perf_counter()
                result, _elapse = engine(box)
                seconds = time.perf_counter() - started
                if best is None or seconds < best:
                    best = seconds
                    text = " ".join(x[1] for x in (result or []))
                    shapes = list(calls)
            if reference is None:
                reference = text
                fidelity = 100.0
            else:
                from rapidfuzz import fuzz
                fidelity = fuzz.ratio(reference, text)
            detail = "  ".join(f"{'x'.join(str(d) for d in s)} {ms * 1000:.0f}ms"
                               for s, ms in shapes)
            print(f"{label:32} {best:9.2f}s {fidelity:8.1f}%  {detail}")
            # Release it before building the next one. The old probe kept all
            # seven alive, and their onnxruntime thread pools competed with the
            # trial being measured — which is what made the first row look fast.
            del engine
            gc.collect()
        except Exception as exc:  # noqa: BLE001
            print(f"{label:32} {'failed':>10}   {type(exc).__name__}: {exc}"[:120])

    during = _busy(idle_before, _cpu_times())
    if during is not None:
        print(f"\nMachine {during:.0f}% busy across the whole probe.")
    print("A shape that does not change is a setting that did not arrive.")
    print("A time that does not move once the shapes do is the machine itself,")
    print("and then the answer is a different engine — Windows has")
    print("Windows.Media.Ocr built in, which this project does not wrap yet.")


if __name__ == "__main__":
    main()
