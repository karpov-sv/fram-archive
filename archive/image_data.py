from dataclasses import dataclass
from functools import lru_cache
import os
import posixpath

import numpy as np
from astropy.io import fits
from django.conf import settings

from fram import calibrate

from .models import Calibrations
from .utils import memoize


FITS_CACHE_SIZE = 8
DARK_CACHE_SIZE = 4
IMAGE_CACHE_SIZE = 4
IMAGE_DATA_MODES = {"raw", "preview", "processed", "analysis", "cutout"}

# A flat field pixel below this carries no usable signal - dividing by it either
# blows up into an infinity, where the flat is exactly zero, or amplifies pure
# noise by a large factor. The extraction pipeline calls these highly vignetted
# regions and masks them out (see extract_photometry.py); here they are left
# un-flatted instead, so that a preview still shows the pixels rather than a
# hole, and they are masked for the analysis just as the pipeline does.
FLAT_MIN = 0.5


@dataclass
class LoadedImage:
    data: np.ndarray
    header: fits.Header
    mask: np.ndarray | None = None


@dataclass(frozen=True)
class FitsKey:
    path: str
    ext: int
    dtype_name: str | None
    mtime_ns: int
    size: int


def resolve_image_path(filename):
    if posixpath.isabs(filename):
        return filename
    return posixpath.join(settings.BASE_DIR, filename)


def _fits_key(filename, *, ext=-1, dtype=np.double):
    path = resolve_image_path(filename)
    stat = os.stat(path)
    dtype_name = None if dtype is None else np.dtype(dtype).name
    return FitsKey(
        path=path,
        ext=ext,
        dtype_name=dtype_name,
        mtime_ns=stat.st_mtime_ns,
        size=stat.st_size,
    )


@memoize(
    timeout=3600,
    make_key=lambda image, type='masterdark': f"calib:{image.id}:{type}",
)
def find_calibration_image(image, type='masterdark'):
    calibs = Calibrations.objects.all()

    calibs = calibs.filter(type=type)

    calibs = calibs.filter(site=image.site)
    calibs = calibs.filter(ccd=image.ccd)
    calibs = calibs.filter(serial=image.serial)

    if type not in ['bias', 'dcurrent', 'masterflat']:
        calibs = calibs.filter(exposure=image.exposure)

    calibs = calibs.filter(cropped_width=image.cropped_width)
    calibs = calibs.filter(cropped_height=image.cropped_height)
    calibs = calibs.filter(binning=image.binning)

    if type in ['masterflat']:
        calibs = calibs.filter(filter=image.filter)

    calibs1 = calibs.filter(night__lte=image.night).order_by('-night')
    if calibs1.first():
        return calibs1.first()

    calibs1 = calibs.filter(night__gte=image.night).order_by('night')
    return calibs1.first()


@lru_cache(maxsize=FITS_CACHE_SIZE)
def _load_fits_cached(key):
    data, header = fits.getdata(key.path, key.ext, header=True)
    if key.dtype_name is not None:
        data = data.astype(np.dtype(key.dtype_name), copy=False)
    return data, header


def _calibration_key(image, type):
    calibration_image = find_calibration_image(image, type)
    if calibration_image is None:
        return None
    return _fits_key(calibration_image.filename, dtype=None)


def _dark_key(image):
    cdark_key = _calibration_key(image, 'masterdark')
    if cdark_key is not None:
        return ('fits', cdark_key)

    bias_key = _calibration_key(image, 'bias')
    dcurrent_key = _calibration_key(image, 'dcurrent')
    if bias_key is not None and dcurrent_key is not None:
        return ('bias_dcurrent', bias_key, dcurrent_key, float(image.exposure or 0.0))

    return None


def _flat_key(image):
    return _calibration_key(image, 'masterflat')


@lru_cache(maxsize=DARK_CACHE_SIZE)
def _load_dark_cached(dark_key):
    if dark_key[0] == 'fits':
        data, _ = _load_fits_cached(dark_key[1])
        return data

    if dark_key[0] == 'bias_dcurrent':
        _, bias_key, dcurrent_key, exposure = dark_key
        bias, _ = _load_fits_cached(bias_key)
        dcurrent, _ = _load_fits_cached(dcurrent_key)
        return bias + exposure * dcurrent

    raise ValueError(f"Unsupported dark key: {dark_key[0]}")


@lru_cache(maxsize=IMAGE_CACHE_SIZE)
def _raw_cropped_cached(science_key):
    data, header = _load_fits_cached(science_key)
    data = data.copy()
    header = header.copy()
    return calibrate.crop_overscans(data, header, subtract=False)


@lru_cache(maxsize=IMAGE_CACHE_SIZE)
def _calibrated_cached(science_key, dark_key):
    data, header = _load_fits_cached(science_key)
    data = data.copy()
    header = header.copy()

    if dark_key is not None:
        dark = _load_dark_cached(dark_key).copy()
        return calibrate.calibrate(data, header, dark=dark)

    return calibrate.crop_overscans(data, header)


@lru_cache(maxsize=IMAGE_CACHE_SIZE)
def _processed_cached(science_key, dark_key, flat_key):
    data, header = _calibrated_cached(science_key, dark_key)
    data = data.copy()
    header = header.copy()

    if flat_key is not None:
        flat, _ = _load_fits_cached(flat_key)
        # The normalization is taken over the whole flat, exactly as the
        # extraction pipeline does it, so that what the archive shows is what the
        # photometry was measured on. Only the divisor is floored: a deeply
        # vignetted pixel would otherwise be amplified without bound, and the odd
        # dead one - there is literally one in some of the flats - turns into an
        # infinity that then spreads through every percentile taken of the frame.
        data *= np.nanmedian(flat) / np.maximum(flat, FLAT_MIN)

    return data, header


def load_image_data(
    image,
    *,
    mode="preview",
    dtype=np.double,
):
    if mode not in IMAGE_DATA_MODES:
        raise ValueError(f"Unsupported image data mode: {mode}")

    science_key = _fits_key(image.filename, dtype=dtype)

    if mode == "raw":
        data, header = _raw_cropped_cached(science_key)
        return LoadedImage(data.copy(), header.copy())

    should_process = _should_process_image(image, mode)
    if not should_process:
        data, header = _load_fits_cached(science_key)
        data = data.copy()
        header = header.copy()
        return LoadedImage(data, header)

    dark_key = None if image.type in {'dark', 'zero'} else _dark_key(image)
    flat_key = None
    if dark_key is not None and image.type != "flat":
        flat_key = _flat_key(image)

    data, header = _processed_cached(
        science_key,
        dark_key,
        flat_key,
    )
    mask = None
    if _should_include_mask(mode):
        mask = data > 50000
        if dark_key is not None:
            dark = _load_dark_cached(dark_key)
            if dark.shape == mask.shape:
                bad_dark = dark > np.median(dark) + 10.0 * np.std(dark)
                mask |= bad_dark
        if flat_key is not None:
            # Highly vignetted regions, as in extract_photometry.py. Their pixels
            # were left un-flatted above, so without this they would enter the
            # analysis carrying values the photometry itself never sees.
            flat, _ = _load_fits_cached(flat_key)
            if flat.shape == mask.shape:
                mask |= flat < FLAT_MIN

    return LoadedImage(data.copy(), header.copy(), None if mask is None else mask.copy())


def _should_process_image(image, mode):
    if mode == "preview":
        return image.type not in {"masterdark", "masterflat", "dcurrent", "bias", "dark"}
    if mode in {"analysis", "cutout"}:
        return image.type not in {"masterdark", "masterflat", "dcurrent", "bias"}
    if mode == "processed":
        return True
    return False


def _should_include_mask(mode):
    return mode == "analysis"
