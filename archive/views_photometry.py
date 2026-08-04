from django.http import HttpResponse, FileResponse, JsonResponse
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_protect
from django.db.models import Q

from django.core.cache import cache

from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np
import json
import hashlib
import pickle
import warnings

from astropy.time import Time
from astropy.stats import mad_std
from astropy.timeseries import LombScargle
from scipy.signal import find_peaks

from .models import Photometry


def radectoxieta(ra, dec, ra0=0, dec0=0):
    ra,dec = [np.asarray(_) for _ in (ra,dec)]
    delta_ra = np.asarray(ra - ra0)

    delta_ra[(ra < 10) & (ra0 > 350)] += 360
    delta_ra[(ra > 350) & (ra0 < 10)] -= 360

    xx = np.cos(dec*np.pi/180)*np.sin(delta_ra*np.pi/180)
    yy = np.sin(dec0*np.pi/180)*np.sin(dec*np.pi/180) + np.cos(dec0*np.pi/180)*np.cos(dec*np.pi/180)*np.cos(delta_ra*np.pi/180)
    xi = (xx/yy)

    xx = np.cos(dec0*np.pi/180)*np.sin(dec*np.pi/180) - np.sin(dec0*np.pi/180)*np.cos(dec*np.pi/180)*np.cos(delta_ra*np.pi/180)
    eta = (xx/yy)

    xi *= 180./np.pi
    eta *= 180./np.pi

    return xi,eta


# How many times a quality cut is re-applied around the updated median
CLIP_ITERATIONS = 3


def clip_column(idx, values, side='upper', nsigma=3.0):
    """Points of `idx` surviving an iterative clip of `values` around its median.

    `side` tells which tail goes: `upper` and `lower` reject the large and the
    small values, `both` keeps a symmetric band. The scale is the median absolute
    deviation of the points still selected.

    A column carrying nothing to cut on - all of it missing, or constant, or a
    selection already emptied by an earlier cut - simply leaves the selection
    alone. Without that the median of an empty slice is a NaN, every comparison
    against it is false, and the light curve silently comes out empty.
    """
    values = np.asarray(values, dtype=float)

    for _ in range(CLIP_ITERATIONS):
        if not np.any(idx):
            break

        # Checked before taking the median, which warns about an all-NaN slice
        # rather than just returning one
        selected = values[idx]
        if not np.any(np.isfinite(selected)):
            break

        median = np.nanmedian(selected)
        sigma = mad_std(selected, ignore_nan=True)

        if not np.isfinite(median) or not np.isfinite(sigma) or sigma <= 0:
            break

        if side == 'upper':
            passed = values <= median + nsigma*sigma
        elif side == 'lower':
            passed = values >= median - nsigma*sigma
        else:
            passed = np.abs(values - median) <= nsigma*sigma

        # Nothing left to converge to once a pass rejects nobody
        if np.sum(idx & passed) == np.sum(idx):
            break

        idx = idx & passed

    return idx


def get_lc(params):
    """Queryset of the measurements matching the search constraints.

    `params` is any mapping of the query parameters, so both `request.GET` and a
    plain dictionary of them will do.
    """
    lc = Photometry.objects.order_by('time')

    night = params.get('night')
    if night and night != 'all':
        lc = lc.filter(image__night=night)

    night1 = params.get('night1')
    if night1:
        lc = lc.filter(image__night__gte=night1)

    night2 = params.get('night2')
    if night2:
        lc = lc.filter(image__night__lte=night2)

    # Filter out bad data
    lc = lc.filter(Q(image__night__lt='20190216') | Q(image__night__gt='20190222'))

    site = params.get('site')
    if site and site != 'all':
        lc = lc.filter(image__site=site)

    fname = params.get('filter')
    if fname and fname != 'all':
        lc = lc.filter(filter=fname)

    ccd = params.get('ccd')
    if ccd and ccd != 'all':
        lc = lc.filter(image__ccd=ccd)

    magerr = params.get('magerr')
    if magerr:
        magerr = float(magerr)
        lc = lc.filter(magerr__lt=magerr)

    nstars = params.get('nstars')
    if nstars:
        nstars = int(nstars)
        lc = lc.filter(nstars__gte=nstars)

    ra = float(params.get('ra'))
    dec = float(params.get('dec'))
    sr = float(params.get('sr', 0.01))

    # Lc with centers within given search radius
    lc = lc.extra(
        where=['q3c_radial_query("photometry_all"."ra", "photometry_all"."dec", %s, %s, %s)'],
        params=(ra, dec, sr),
    )

    return lc


# Fewest measurements a band needs before it is shown, and searched, at all. A
# single point is nothing to draw a light curve from, and it carries no
# information for the period search either: centring a band on its own median
# leaves a lone point at exactly zero, which adds nothing but its weight to the
# normalization.
MIN_POINTS_PER_FILTER = 2


def displayed_mask(filters, idx0, minimum=MIN_POINTS_PER_FILTER):
    """Of the points passing the cuts, the ones that actually reach the plot."""
    mask = np.zeros_like(idx0)

    for fn in np.unique(filters):
        idx = idx0 & (filters == fn)

        if np.sum(idx) >= minimum:
            mask |= idx

    return mask


# The query parameters the data themselves depend on. Everything else - the
# resolved name, the plot size, the output mode - only affects the presentation,
# so it must not take part in the cache key below.
LC_PARAMS = [
    'ra', 'dec', 'sr', 'night', 'night1', 'night2', 'site', 'ccd', 'filter',
    'magerr', 'nstars', 'nofiltering', 'sigma',
]

LC_CACHE_TIMEOUT = 600

# Longer light curves are served but not kept: a wide cone may cover a lot of
# stars at once, and an entry costs roughly 150 KiB per thousand points
LC_CACHE_MAX_POINTS = 20000


def lc_query_params(request):
    """Stable, hashable form of the parameters the data depend on."""
    return tuple((_, request.GET.get(_)) for _ in LC_PARAMS)


def cached_lc(request):
    """`build_lc` for a request, keeping the result for the other views.

    The same light curve is asked for by the plot and then by the period search,
    so hold on to it instead of querying the database anew every time.
    """
    params = lc_query_params(request)
    key = 'lc:' + hashlib.md5(pickle.dumps(params)).hexdigest()

    data = cache.get(key)
    if data is not None:
        return data

    data = build_lc(dict(params))

    if len(data['times']) <= LC_CACHE_MAX_POINTS:
        cache.set(key, data, LC_CACHE_TIMEOUT)

    return data


def build_lc(params):
    """Load a light curve and bring it into the form it is displayed in.

    Returns the measurement columns together with `idx0`, the points passing the
    quality cuts - the very ones the plot draws and the period search runs on.
    """
    lc = get_lc(params)

    # Fetch all data in a single query instead of iterating 10+ times
    data = list(
        lc.values_list(
            'time', 'image__site', 'image__ccd', 'filter', 'ra', 'dec',
            'mag', 'magerr', 'flags', 'fwhm', 'std', 'nstars',
            'color_term', 'zp_std', 'final_frac',
            # Identify the frame every measurement was made on, so that the plot
            # may show the very pixels behind a point
            'image__id', 'image__night',
        )
    )

    if data:
        times, sites, ccds, filters, ras, decs, mags, magerrs, flags, fwhms, stds, nstars, color_term, zp_std, final_frac, image_ids, nights = zip(*data)
        times = np.array(times)
        sites = np.array(sites)
        ccds = np.array(ccds)
        filters = np.array(filters)
        ras = np.array(ras)
        decs = np.array(decs)
        mags = np.array(mags)
        magerrs = np.array(magerrs)
        flags = np.array(flags)
        fwhms = np.array(fwhms)
        stds = np.array(stds)
        nstars = np.array(nstars)
        color_term = np.array(color_term)
        zp_std = np.array(zp_std)
        final_frac = np.array(final_frac)
        # Object arrays, as either column may be NULL for a measurement whose
        # frame is gone from the archive
        image_ids = np.array(image_ids, dtype=object)
        nights = np.array(nights, dtype=object)
    else:
        times = sites = ccds = filters = ras = decs = mags = magerrs = flags = fwhms = stds = nstars = color_term = zp_std = final_frac = image_ids = nights = np.array([])

    mjds = Time(times).mjd if len(times) else []

    cols = np.array([{'B':'blue', 'V':'green', 'R':'red', 'I':'orange', 'z':'magenta'}.get(_, 'black') for _ in filters])

    filtering = not params.get('nofiltering')

    # Quality cuts
    idx0 = np.ones_like(mags, dtype=bool)
    if filtering:
        mask = np.zeros_like(mags, dtype=bool)

        idx0 &= flags < 2

        for fn in np.unique(filters):
            idx = idx0 & (filters == fn)

            idx = clip_column(idx, stds, 'upper')
            idx = clip_column(idx, fwhms, 'upper')
            idx = clip_column(idx, color_term, 'both')
            idx = clip_column(idx, zp_std, 'upper')
            idx = clip_column(idx, final_frac, 'lower')

            mask |= idx

        idx0 = mask

    # Optional clipping of the magnitudes themselves, off unless asked for. It is
    # kept apart from the cuts above on purpose: those reject the measurements
    # known to be bad, whereas this one rejects whatever deviates, and so removes
    # the deep minima of a genuine variable along with the outliers.
    #
    # Grouped by camera as well as by filter, which the cuts above have no need
    # to be: they clip quantities describing a frame, while this one clips the
    # magnitude, and the zero points of two cameras need not agree closely enough
    # for a common median to be meaningful. Clipping around one would reject the
    # camera that sits furthest from it rather than the measurements that deviate.
    try:
        sigma = float(params.get('sigma') or 0)
    except ValueError:
        sigma = 0

    # Anything not positive is simply off, and is reported as such
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = 0

    if sigma > 0 and np.any(idx0):
        mask = np.zeros_like(idx0)

        for cc in np.unique(ccds):
            for fn in np.unique(filters):
                idx = idx0 & (ccds == cc) & (filters == fn)
                mask |= clip_column(idx, mags, 'both', sigma)

        idx0 = mask

    return {
        'sigma': sigma,
        'times': times, 'mjds': np.asarray(mjds), 'sites': sites, 'ccds': ccds,
        'filters': filters, 'cols': cols, 'ras': ras, 'decs': decs,
        'mags': mags, 'magerrs': magerrs, 'flags': flags, 'fwhms': fwhms,
        'stds': stds, 'nstars': nstars, 'color_term': color_term,
        'image_ids': image_ids, 'nights': nights,
        'idx0': idx0, 'filtering': filtering,
    }


# Shortest period searched by default, in days. The archive visits a field a
# handful of times a night at best, so shorter periods are mostly aliases anyway,
# and the frequency grid needed for them grows accordingly.
PERIOD_MIN = 0.05
PERIOD_SAMPLES_PER_PEAK = 5

# The grid is what the search costs - it grows with the time span and with the
# shortest period, and is independent of the number of points - so cap it to keep
# a single request within a second or so. The archive spans over a decade, which
# is a far longer baseline than the survey favor2ext searches.
PERIOD_MAX_FREQUENCIES = 500000

# The full periodogram is far too big to ship, so it is sent decimated to this
# many points, keeping the maxima rather than sampling them away
PERIOD_PLOT_POINTS = 2000

PERIOD_MIN_POINTS = 10
PERIOD_NPEAKS = 5
PERIOD_CACHE_TIMEOUT = 600

# Periods the sampling itself imprints on any periodogram from the ground: the
# solar and sidereal day with their harmonics, and the year
PERIOD_ALIASES = [1.0, 0.5, 1/3, 0.99726957, 0.49863478, 365.25]


def find_period(mjds, mags, magerrs, pmin, pmax):
    """Lomb-Scargle periodogram of a light curve and its highest peaks."""
    ls = LombScargle(mjds, mags, magerrs)

    span = np.max(mjds) - np.min(mjds)
    fmin, fmax = 1.0/pmax, 1.0/pmin

    nfreq = int(np.ceil(PERIOD_SAMPLES_PER_PEAK * span * (fmax - fmin)))
    truncated = nfreq > PERIOD_MAX_FREQUENCIES
    nfreq = int(np.clip(nfreq, 100, PERIOD_MAX_FREQUENCIES))

    freq = np.linspace(fmin, fmax, nfreq)
    power = ls.power(freq)

    # Highest local maxima, so that the neighbouring samples of one and the same
    # peak are not reported as separate detections
    idx, _ = find_peaks(power)
    if not len(idx):
        idx = np.array([np.argmax(power)])
    idx = idx[np.argsort(power[idx])[::-1]][:PERIOD_NPEAKS]

    peaks = []
    for i in idx:
        # The analytic false alarm probability is not always computable, and
        # degenerates for a handful of points, so report it only when it is sane
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                fap = float(ls.false_alarm_probability(power[i], method='baluev'))
            if not np.isfinite(fap):
                fap = None
        except Exception:
            fap = None

        peaks.append({
            'period': round(float(1.0/freq[i]), 6),
            'power': round(float(power[i]), 4),
            'fap': fap,
        })

    # Decimate for display by keeping the largest value of every bin, so that a
    # narrow peak survives instead of falling between the samples
    nbins = min(PERIOD_PLOT_POINTS, nfreq)
    edges = np.linspace(0, nfreq, nbins + 1).astype(int)
    pp, pw = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        if b > a:
            j = a + int(np.argmax(power[a:b]))
            # Rounded, as the full precision only inflates the response
            pp.append(round(float(1.0/freq[j]), 6))
            pw.append(round(float(power[j]), 4))

    return {
        'periods': pp, 'power': pw, 'peaks': peaks,
        'nfreq': nfreq, 'truncated': truncated,
        'pmin': float(pmin), 'pmax': float(pmax), 'span': float(span),
        'aliases': [_ for _ in PERIOD_ALIASES if pmin <= _ <= pmax],
    }


def period(request):
    """Search the displayed light curve for a period."""
    data = cached_lc(request)

    # The very points the plot draws, so that the two agree on how many there are
    idx = displayed_mask(data['filters'], data['idx0'])
    mjds = np.asarray(data['mjds'], dtype=float)[idx]
    mags = np.asarray(data['mags'], dtype=float)[idx]
    magerrs = np.asarray(data['magerrs'], dtype=float)[idx]
    filters = np.asarray(data['filters'])[idx]

    # A measurement missing either of these carries nothing to transform
    good = np.isfinite(mjds) & np.isfinite(mags) & np.isfinite(magerrs) & (magerrs > 0)
    mjds, mags, magerrs, filters = mjds[good], mags[good], magerrs[good], filters[good]

    if len(mjds) < PERIOD_MIN_POINTS:
        return JsonResponse({
            'error': 'Too few points (%d) to search for a period' % len(mjds),
        }, status=400)

    # Every band sits at a magnitude of its own - here they are whole magnitudes
    # apart, an order of magnitude more than the variability being looked for -
    # so pooling them as they are would find the color of the star rather than
    # its period. Centring each on its own median puts them on a common scale.
    # Their amplitudes still differ, which the transform tolerates.
    bands = np.unique(filters)
    for fn in bands:
        sel = filters == fn
        mags[sel] -= np.median(mags[sel])

    span = np.max(mjds) - np.min(mjds)

    try:
        pmin = float(request.GET.get('pmin') or PERIOD_MIN)
    except ValueError:
        pmin = PERIOD_MIN

    try:
        pmax = float(request.GET.get('pmax') or 0.5*span)
    except ValueError:
        pmax = 0.5*span

    pmin = max(pmin, 1e-4)
    pmax = min(max(pmax, 2*pmin), span)

    if not np.isfinite(span) or span <= 0:
        return JsonResponse({
            'error': 'The measurements span no time at all',
        }, status=400)

    key = 'period:' + hashlib.md5(pickle.dumps(
        (lc_query_params(request), pmin, pmax))).hexdigest()

    result = cache.get(key)
    if result is None:
        result = find_period(mjds, mags, magerrs, pmin, pmax)
        cache.set(key, result, PERIOD_CACHE_TIMEOUT)

    result = dict(result)
    result['npoints'] = int(len(mjds))
    result['filters'] = [str(_) for _ in bands]
    # Reference epoch for folding, so that the phase does not depend on the
    # window the light curve happens to be displayed in
    result['epoch'] = float(np.min(mjds))

    return JsonResponse(result)


def lc(request, mode="jpg", size=800):
    data = cached_lc(request)

    times, mjds = data['times'], data['mjds']
    sites, ccds, filters, cols = data['sites'], data['ccds'], data['filters'], data['cols']
    ras, decs = data['ras'], data['decs']
    mags, magerrs = data['mags'], data['magerrs']
    flags, fwhms = data['flags'], data['fwhms']
    stds, nstars, color_term = data['stds'], data['nstars'], data['color_term']
    image_ids, nights = data['image_ids'], data['nights']
    idx0 = data['idx0']

    ra = float(request.GET.get('ra'))
    dec = float(request.GET.get('dec'))
    sr = float(request.GET.get('sr', 0.01))
    name = request.GET.get('name')

    if name in ['sexadecimal', 'degrees']:
        name = None

    if name:
        title = '%s - ' % name
    else:
        title = ''

    # The count is of what is drawn below, not of what the query returned: with
    # the quality cuts on, the two differ by a factor of about two, and the
    # caption used to advertise the larger of them
    shown = np.sum(displayed_mask(filters, idx0))

    title += '%.4f %.3f %.3f - ' % (ra, dec, sr)
    if shown != len(mags):
        title += '%d of %d pts' % (shown, len(mags))
    else:
        title += '%d pts' % len(mags)

    # Worth saying, as it is off by default and does reject real variability
    if data['sigma'] > 0:
        title += ' - clipped at %g sigma' % data['sigma']

    xi,eta = radectoxieta(ras, decs, ra, dec)
    xi *= 3600
    eta *= 3600

    if mode == 'jpeg':
        # Plot lc
        fig = Figure(facecolor='white', dpi=72, figsize=(size/72,0.5*size/72), tight_layout=True)
        ax = fig.add_subplot(111)
        ax.grid(True, alpha=0.1, color='gray')

        for fn in np.unique(filters):
            idx = idx0 & (filters == fn)

            if len(mags[idx]) < MIN_POINTS_PER_FILTER:
                continue

            ax.errorbar(times[idx], mags[idx], magerrs[idx], fmt='.', color=cols[idx][0], capsize=0, alpha=0.3)
            ax.scatter(times[idx], mags[idx], marker='.', c=cols[idx][0])
            ax.invert_yaxis()

        ax.invert_yaxis()

        ax.set_title(title)

        canvas = FigureCanvas(fig)

        response = HttpResponse(content_type='image/jpeg')
        canvas.print_jpg(response)

        return response

    elif mode == 'json':
        lcs = []

        for fn in np.unique(filters):
            idx = idx0 & (filters == fn)

            if len(mags[idx]) < MIN_POINTS_PER_FILTER:
                continue

            times_idx = [_.isoformat() for _ in times[idx]]

            lcs.append({'filter': fn, 'color': cols[idx][0],
                        # Where the star was actually detected on every frame, as
                        # opposed to where it was asked for. The photometry is
                        # extracted from a free detection rather than forced at a
                        # catalogue position, so the two differ by a pixel or two.
                        'ras': list(ras[idx]), 'decs': list(decs[idx]),
                        'times': times_idx, 'mjds': list(mjds[idx]), 'xi': list(xi[idx]), 'eta': list(eta[idx]),
                        'mags': list(mags[idx]), 'magerrs': list(magerrs[idx]), 'flags': list(flags[idx]),
                        'fwhms': list(fwhms[idx]), 'stds': list(stds[idx]), 'nstars': list(nstars[idx]),
                        'sites': list(sites[idx]), 'ccds': list(ccds[idx]), 'color_term': list(color_term[idx]),
                        'image_ids': [None if _ is None else int(_) for _ in image_ids[idx]],
                        'nights': list(nights[idx])})

        data = {'name': name, 'title': title, 'ra': ra, 'dec': dec, 'sr': sr, 'lcs': lcs}

        return HttpResponse(json.dumps(data, default=str), content_type="application/json")

    elif mode == 'text':
        response = HttpResponse(request, content_type='text/plain')

        response['Content-Disposition'] = 'attachment; filename=lc_full_%s_%s_%s.txt' % (ra, dec, sr)

        print('# Date Time MJD Site CCD Filter Mag Magerr Flags FWHM Std Nstars', file=response)

        for _ in range(len(times)):
            print(times[_], mjds[_], sites[_], ccds[_], filters[_], mags[_], magerrs[_], flags[_], fwhms[_], stds[_], nstars[_], file=response)

        return response

    elif mode == 'mjd':
        response = HttpResponse(request, content_type='text/plain')

        response['Content-Disposition'] = 'attachment; filename=lc_mjd_%s_%s_%s.txt' % (ra, dec, sr)

        if len(np.unique(filters)) == 1:
            single = True
        else:
            single = False

        if single:
            print('# MJD Mag Magerr', file=response)
        else:
            print('# MJD Mag Magerr Filter', file=response)

        idx = idx0

        for _ in range(len(times[idx])):
            if single:
                print(mjds[idx][_], mags[idx][_], magerrs[idx][_], file=response)
            else:
                print(mjds[idx][_], mags[idx][_], magerrs[idx][_], filters[idx][_], file=response)

        return response
