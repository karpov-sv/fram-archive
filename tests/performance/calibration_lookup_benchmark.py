#!/usr/bin/env python3
"""
Simple benchmark for calibration lookups and calibration processing.
"""
import argparse
import os
import posixpath
import random
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archive.settings")

import django  # noqa: E402

django.setup()

from django.core.cache import cache  # noqa: E402
from django.conf import settings  # noqa: E402

import numpy as np  # noqa: E402
from astropy.io import fits  # noqa: E402

from fram import calibrate  # noqa: E402

from archive.models import Images  # noqa: E402
from archive.views_images import find_calibration_image  # noqa: E402


SKIP_TYPES = {"masterdark", "masterflat", "bias", "dcurrent"}


def timed_find_calibration(image, calib_type, durations):
    start = time.perf_counter()
    result = find_calibration_image(image, calib_type)
    durations.append(time.perf_counter() - start)
    return result


def timed_load_calibration_data(calibration, durations):
    start = time.perf_counter()
    data = fits.getdata(calibration.filename, -1)
    durations.append(time.perf_counter() - start)
    return data


def load_image_data(image):
    filename = posixpath.join(settings.BASE_DIR, image.filename)
    start = time.perf_counter()
    data = fits.getdata(filename, -1)
    header = fits.getheader(filename, -1)
    duration = time.perf_counter() - start
    return data, header, duration


def calibrate_image(image, data, header):
    find_durations = []
    calib_load_durations = []
    calib_apply_durations = []

    if image.type in SKIP_TYPES:
        start = time.perf_counter()
        data, header = calibrate.crop_overscans(data, header, subtract=False)
        calib_apply_durations.append(time.perf_counter() - start)
        return find_durations, calib_load_durations, calib_apply_durations

    dark = None
    if image.type not in {"dark", "zero"}:
        masterdark = timed_find_calibration(image, "masterdark", find_durations)

        if masterdark is not None:
            dark = timed_load_calibration_data(masterdark, calib_load_durations)
        else:
            bias = timed_find_calibration(image, "bias", find_durations)
            dcurrent = timed_find_calibration(image, "dcurrent", find_durations)

            if bias is not None and dcurrent is not None:
                bias_data = timed_load_calibration_data(bias, calib_load_durations)
                dcurrent_data = timed_load_calibration_data(
                    dcurrent, calib_load_durations
                )
                dark = bias_data + image.exposure * dcurrent_data

    if dark is not None:
        start = time.perf_counter()
        data, header = calibrate.calibrate(data, header, dark=dark)
        apply_duration = time.perf_counter() - start

        if image.type not in {"flat1"}:
            masterflat = timed_find_calibration(image, "masterflat", find_durations)
            if masterflat is not None:
                flat = timed_load_calibration_data(masterflat, calib_load_durations)
                start = time.perf_counter()
                data *= np.median(flat) / flat
                apply_duration += time.perf_counter() - start

        calib_apply_durations.append(apply_duration)
    else:
        start = time.perf_counter()
        data, header = calibrate.crop_overscans(data, header)
        calib_apply_durations.append(time.perf_counter() - start)

    return find_durations, calib_load_durations, calib_apply_durations


def main():
    parser = argparse.ArgumentParser(
        description="Measure calibration lookup and processing timing."
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="Number of random images to sample.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible sampling.",
    )
    parser.add_argument(
        "--keep-cache",
        action="store_true",
        help="Do not clear the Django cache before benchmarking.",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    if not args.keep_cache:
        cache.clear()

    images = Images.objects.filter(type="object").order_by("id")
    total = images.count()
    if total == 0:
        print("No images found with type=object.")
        return 1

    if args.iterations <= total:
        offsets = random.sample(range(total), args.iterations)
    else:
        offsets = [random.randrange(total) for _ in range(args.iterations)]

    image_load_durations = []
    find_durations = []
    calib_load_durations = []
    calib_apply_durations = []

    for offset in offsets:
        image = images[offset]
        data, header, image_load_duration = load_image_data(image)
        image_load_durations.append(image_load_duration)

        found, loaded, applied = calibrate_image(image, data, header)
        find_durations.extend(found)
        calib_load_durations.extend(loaded)
        calib_apply_durations.extend(applied)

    if not image_load_durations:
        print("No image loads were performed.")
        return 1

    mean_image_load = sum(image_load_durations) / len(image_load_durations)
    print(f"images sampled: {len(image_load_durations)}")
    print(f"mean image load: {mean_image_load * 1000:.2f} ms")

    if find_durations:
        mean_find = sum(find_durations) / len(find_durations)
        print(f"find_calibration_image calls: {len(find_durations)}")
        print(f"mean find_calibration_image: {mean_find * 1000:.2f} ms")
    else:
        print("find_calibration_image calls: 0")

    if calib_load_durations:
        mean_calib_load = sum(calib_load_durations) / len(calib_load_durations)
        print(f"calibration image loads: {len(calib_load_durations)}")
        print(f"mean calibration image load: {mean_calib_load * 1000:.2f} ms")
    else:
        print("calibration image loads: 0")

    if calib_apply_durations:
        mean_calib_apply = sum(calib_apply_durations) / len(calib_apply_durations)
        print(f"calibration applies: {len(calib_apply_durations)}")
        print(f"mean calibration apply: {mean_calib_apply * 1000:.2f} ms")
    else:
        print("calibration applies: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
