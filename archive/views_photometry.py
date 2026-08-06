from django.http import HttpResponse, FileResponse, JsonResponse
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_protect

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

from .models import photometry_route_for
from .utils import db_query


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
    """Fetch the measurements matching the search constraints as a list of
    dicts keyed by column name.

    `params` is any mapping of the query parameters, so both `request.GET` and
    a plain dictionary of them will do.

    When both `site` and `ccd` are pinned to concrete values, the FROM clause
    targets the corresponding child of `photometry_all` directly. Cross-
    partition cone searches otherwise pay a full round of index probes on
    every child, which on cold cache is the dominant cost for 3–15" cones.
    """
    site = params.get('site')
    ccd = params.get('ccd')
    route = photometry_route_for(site, ccd)

    where = ['(i.night < %s OR i.night > %s)']
    sql_params = ['20190216', '20190222']

    night = params.get('night')
    if night and night != 'all':
        where.append('i.night = %s')
        sql_params.append(night)

    night1 = params.get('night1')
    if night1:
        where.append('i.night >= %s')
        sql_params.append(night1)

    night2 = params.get('night2')
    if night2:
        where.append('i.night <= %s')
        sql_params.append(night2)

    # Skip WHERE clauses on axes the routed table already narrows on. A
    # specific partition narrows both site and ccd; a group view narrows only
    # ccd (its member children span multiple sites).
    if site and site != 'all' and not route.narrows_site:
        where.append('i.site = %s')
        sql_params.append(site)

    if ccd and ccd != 'all' and not route.narrows_ccd:
        where.append('i.ccd = %s')
        sql_params.append(ccd)

    fname = params.get('filter')
    if fname and fname != 'all':
        where.append('p.filter = %s')
        sql_params.append(fname)

    magerr = params.get('magerr')
    if magerr:
        where.append('p.magerr < %s')
        sql_params.append(float(magerr))

    nstars = params.get('nstars')
    if nstars:
        where.append('p.nstars >= %s')
        sql_params.append(int(nstars))

    ra = float(params.get('ra'))
    dec = float(params.get('dec'))
    sr = float(params.get('sr', 0.01))
    where.append('q3c_radial_query(p.ra, p.dec, %s, %s, %s)')
    sql_params.extend((ra, dec, sr))

    # `p.*` pulls every Photometry column without us having to enumerate them;
    # from `images` we only need the four extras that build_lc reads. The
    # table name comes from `photometry_route_for`'s hardcoded whitelist, so
    # the string interpolation is safe.
    sql = (
        'SELECT p.*, i.site, i.ccd, i.id AS image_id, i.night '
        'FROM ' + route.table + ' AS p '
        'INNER JOIN images AS i ON p.image = i.id '
        'WHERE ' + ' AND '.join(where) +
        ' ORDER BY p.time'
    )

    return db_query(sql, sql_params, simplify=False) or []


# Default largest gap between two measurements still counted as one visit, in
# seconds. Some of the target scripts take several images in a row before moving
# on, so the measurements arrive in clumps a minute or two apart separated by
# much larger gaps - on HD 7252 three quarters of the intervals within a band are
# under ten minutes, while a survey field such as the one M31 falls in shows no
# clumping at all. Hence an option rather than a default.
AVERAGE_WINDOW = 600.0

# A group is additionally not allowed to span more than this many times the
# window, so that a long continuous sequence - a follow-up, say - is binned
# rather than collapsed into a single point.
AVERAGE_MAX_SPAN_FACTOR = 3

# How the measurements of a group are combined
AVERAGE_MODES = ['mean', 'median', 'clipped']
AVERAGE_MODE = 'mean'

# How far a measurement may deviate from the median of its group, in units of the
# expected uncertainty of that deviation, before the `clipped` mode drops it.
# Kept loose, as the point is to remove the grossly spoiled measurements rather
# than to trim the distribution.
AVERAGE_CLIP_SIGMA = 5.0

# Systematic scatter of the photometry, added in quadrature to the errors when
# deciding what deviates. The reported errors are photometric only, while the
# light curves have an irreducible floor of about this size, so without it a
# bright star with tiny errors would have its perfectly normal points rejected.
AVERAGE_CLIP_FLOOR = 0.02


def group_close_measurements(times, keys, window=AVERAGE_WINDOW):
    """Assign a group id to measurements that are close in time.

    Measurements sharing the same `key` - the site, the camera and the filter -
    and separated by no more than `window` seconds from the previous one belong to
    the same group. Grouping is done per key, so two sites observing the same star
    on the same night, or two cameras at one site, do not interfere with each
    other, and no average ever mixes zero points that need not agree.
    """
    groups = np.full(len(times), -1, dtype=int)
    gid = 0

    for key in set(keys):
        sel = np.where(keys == key)[0]
        sel = sel[np.argsort(times[sel])]

        start = None
        prev = None

        for i in sel:
            if prev is not None:
                gap = (times[i] - prev).total_seconds()
                span = (times[i] - start).total_seconds()
                if gap > window or span > AVERAGE_MAX_SPAN_FACTOR*window:
                    gid += 1
                    start = times[i]
            else:
                start = times[i]

            groups[i] = gid
            prev = times[i]

        gid += 1

    return groups


def clip_group(mags, magerrs, sigma=AVERAGE_CLIP_SIGMA, floor=AVERAGE_CLIP_FLOOR):
    """Members of a group not deviating from its median.

    The deviation of every measurement from the median of the group is compared
    with what its own error, and the error of the median itself, allow. This is
    what an inverse-variance weighted mean cannot do on its own: a spuriously
    bright measurement is by construction assigned a small error, so it comes with
    an enormous weight and the average follows it instead of the good points.
    Fewer than three measurements are left alone, as with two of them there is no
    way to tell which one is the outlier.
    """
    idx = np.ones(len(mags), dtype=bool)

    if len(mags) < 3:
        return idx

    median = np.median(mags)

    # Uncertainty of the median, taken as that of a typical member. Being a rough
    # scale rather than a rigorous error, it needs no sqrt(N) refinement.
    err0 = np.median(magerrs)

    with np.errstate(invalid='ignore'):
        scale = np.sqrt(magerrs**2 + err0**2 + 2*floor**2)
        passed = np.abs(mags - median) < sigma*scale

    # A group where the test is unusable (missing errors, or everything rejected)
    # is kept whole rather than silently emptied
    if not np.all(np.isfinite(scale)) or not np.any(passed):
        return idx

    return passed


# Combined the same way as the magnitudes, but without any weighting
AVERAGE_PLAIN_COLUMNS = ['ras', 'decs', 'fwhms', 'stds', 'nstars', 'color_term']

# Taken from the earliest measurement of a group: the light curve point sits at
# the mean time, which for an incomplete group belongs to no frame at all, so
# these have to name an actual one for the cutout popup to open
AVERAGE_FIRST_COLUMNS = ['image_ids', 'nights']


def average_lc(data, window=AVERAGE_WINDOW, mode=AVERAGE_MODE):
    """Average measurements clustered in time, improving the accuracy.

    In the `mean` mode the magnitudes within a group are combined with an
    inverse-variance weighted mean, so the uncertainty of a group of N similar
    points shrinks roughly as sqrt(N). The `median` mode takes their median
    instead, which resists a single spoiled measurement at the cost of a larger
    uncertainty. The `clipped` mode first drops the members deviating from the
    median of their group (see `clip_group`) and then takes the weighted mean of
    the rest, keeping the precision of the mean where nothing is wrong. Flags are
    OR-ed together, and `npoints` reports how many measurements went into every
    result - which in the `clipped` mode is the number actually used, not the
    number the group started with.
    """
    combine = np.median if mode == 'median' else np.mean

    keys = np.array(['%s_%s_%s' % (s, c, f)
                     for s, c, f in zip(data['sites'], data['ccds'], data['filters'])])
    groups = group_close_measurements(data['times'], keys, window=window)

    result = {_: [] for _ in data}
    result['npoints'] = []

    for gid in sorted(set(groups)):
        idx = groups == gid

        if mode == 'clipped':
            # The rejected members drop out of every column, not just of the
            # magnitude, so that the result describes the same measurements
            sel = np.where(idx)[0]
            idx = np.zeros_like(idx)
            idx[sel[clip_group(data['mags'][sel], data['magerrs'][sel])]] = True

        n = int(np.sum(idx))

        mag = np.asarray(data['mags'][idx], dtype=float)
        magerr = np.asarray(data['magerrs'][idx], dtype=float)

        if mode == 'median':
            result['mags'].append(np.median(mag))

            # The median is a noisier estimator than the mean: asymptotically its
            # variance is larger by pi/2. For one or two points it is just their
            # unweighted mean, so the plain error of the mean applies there.
            sigma = np.sqrt(np.mean(magerr**2)/n)
            result['magerrs'].append(sigma if n < 3 else np.sqrt(0.5*np.pi)*sigma)
        else:
            # Inverse-variance weights, falling back to equal ones if the errors
            # are missing or degenerate
            with np.errstate(divide='ignore', invalid='ignore'):
                weights = 1.0/magerr**2
            if not np.all(np.isfinite(weights)) or np.sum(weights) <= 0:
                weights = np.ones_like(mag)

            result['mags'].append(np.sum(weights*mag)/np.sum(weights))
            result['magerrs'].append(np.sqrt(1.0/np.sum(weights)))

        # Central time of the group
        mjd = np.asarray(data['mjds'][idx], dtype=float)
        result['mjds'].append(combine(mjd))
        result['times'].append(Time(combine(mjd), format='mjd').datetime)

        # Any problem with a constituent frame marks the average. Kept as float
        # to match the type of the non-averaged points.
        gflags = np.nan_to_num(np.asarray(data['flags'][idx], dtype=float)).astype(int)
        result['flags'].append(float(np.bitwise_or.reduce(gflags)))

        # All three are the key, so they are constant within a group
        for _ in ['sites', 'ccds', 'filters']:
            result[_].append(data[_][idx][0])

        first = int(np.argmin(mjd))
        for _ in AVERAGE_FIRST_COLUMNS:
            result[_].append(data[_][idx][first])

        for _ in AVERAGE_PLAIN_COLUMNS:
            result[_].append(combine(np.asarray(data[_][idx], dtype=float)))

        result['npoints'].append(n)

    return {_: np.array(result[_]) for _ in result}


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


# The colors that may be displayed, as the pairs of bands they are made of. The
# archive has B, V, R and I of a star; z sits on one camera alone and N is no
# photometric band at all, so neither has a companion to make a color with.
COLOR_PAIRS = [('B', 'V'), ('V', 'R'), ('V', 'I'), ('R', 'I')]

# Where the colors are drawn. Deliberately unlike the colors of the bands
# themselves, since the two sets share one legend.
COLOR_COLORS = {'B-V': '#8c564b', 'V-R': '#9467bd', 'V-I': '#17becf', 'R-I': '#7f7f7f'}

# Largest separation in time between the two measurements of a color, in days.
# The real constraint is that they belong to the same night; this one only backs
# it up for a measurement whose frame has since left the archive, and which has
# thus no night to be compared by.
COLOR_WINDOW = 0.5


def nearest_index(values, others):
    """For every element of `values`, the index of the closest element of `others`.

    Both are expected sorted, which is what lets it cost a binary search per
    element instead of a full scan.
    """
    pos = np.searchsorted(others, values)
    left = np.clip(pos - 1, 0, len(others) - 1)
    right = np.clip(pos, 0, len(others) - 1)

    closer = np.abs(values - others[left]) <= np.abs(values - others[right])

    return np.where(closer, left, right)


def pair_bands(mjds1, mjds2, window=COLOR_WINDOW):
    """Match the measurements of two bands that were taken together.

    Two measurements make a color when each is the closest the other has, which
    is what keeps the matching one to one: three exposures in B and one in V
    yield a single color rather than three sharing the same V, and the two that
    lost are simply dropped. A pair separated by more than `window` days is not
    a pair at all, however close the two are to each other.

    Returns the indices into `mjds1` and `mjds2` of the measurements that paired
    up, in no particular order.
    """
    none = np.array([], dtype=int)

    if not len(mjds1) or not len(mjds2):
        return none, none

    order1, order2 = np.argsort(mjds1), np.argsort(mjds2)
    sorted1, sorted2 = mjds1[order1], mjds2[order2]

    to2 = nearest_index(sorted1, sorted2)
    to1 = nearest_index(sorted2, sorted1)

    # The closest measurement of the other band has to point back
    i1 = np.where(to1[to2] == np.arange(len(sorted1)))[0]
    i2 = to2[i1]

    close = np.abs(sorted1[i1] - sorted2[i2]) <= window

    return order1[i1[close]], order2[i2[close]]


def compute_colors(data, idx, window=COLOR_WINDOW):
    """Colors of the star, from the measurements of two bands taken together.

    A color is the difference of two magnitudes measured on different frames, so
    it only means anything when the two were taken close enough in time for the
    star not to have moved between them. They are required to belong to the same
    night of the same camera, and then to be each other's nearest measurement
    within `window` days.

    The camera is part of that on purpose: the zero points of two of them need
    not agree closely enough for their difference to be a color of the star
    rather than one of the instruments. It costs nothing here, as every camera of
    the archive carries the whole filter set.
    """
    mjds = np.asarray(data['mjds'], dtype=float)
    mags = np.asarray(data['mags'], dtype=float)
    magerrs = np.asarray(data['magerrs'], dtype=float)
    filters = np.asarray(data['filters'])
    sites, ccds = np.asarray(data['sites']), np.asarray(data['ccds'])
    nights = np.asarray(data['nights'], dtype=object)

    # A measurement missing either of these carries nothing to a color
    idx = idx & np.isfinite(mjds) & np.isfinite(mags) & np.isfinite(magerrs)

    # The measurements of every camera, night and band, so that the matching
    # below looks at one night at a time instead of scanning the whole curve
    # once per color it makes
    groups = {}
    for i in np.where(idx)[0]:
        groups.setdefault((sites[i], ccds[i], nights[i], filters[i]), []).append(i)

    # Deduplicated rather than sorted, as a night may well be missing and None
    # does not compare with a string
    visits = list(dict.fromkeys(_[:3] for _ in groups))

    colors = []

    for f1, f2 in COLOR_PAIRS:
        pairs1, pairs2 = [], []

        for visit in visits:
            sel1 = groups.get(visit + (f1,))
            sel2 = groups.get(visit + (f2,))

            if not sel1 or not sel2:
                continue

            sel1, sel2 = np.array(sel1), np.array(sel2)
            i1, i2 = pair_bands(mjds[sel1], mjds[sel2], window=window)

            pairs1.append(sel1[i1])
            pairs2.append(sel2[i2])

        if not pairs1:
            continue

        i1, i2 = np.concatenate(pairs1), np.concatenate(pairs2)

        # Held to the same minimum as a band, and for the same reason
        if len(i1) < MIN_POINTS_PER_FILTER:
            continue

        # A color sits at the mean time of the two measurements it is made of
        cmjds = 0.5*(mjds[i1] + mjds[i2])

        order = np.argsort(cmjds)
        i1, i2, cmjds = i1[order], i2[order], cmjds[order]

        name = '%s-%s' % (f1, f2)

        colors.append({
            'name': name,
            'color': COLOR_COLORS.get(name, 'black'),
            'mjds': [float(_) for _ in cmjds],
            'times': [Time(_, format='mjd').datetime.isoformat() for _ in cmjds],
            'values': [float(_) for _ in mags[i1] - mags[i2]],
            'errors': [float(_) for _ in np.hypot(magerrs[i1], magerrs[i2])],
            # How far apart the two measurements actually were, in seconds. A
            # filter wheel cycles in tens of them, so a color of a wholly
            # different order is one made at two ends of a night.
            'dts': [float(_) for _ in 86400*np.abs(mjds[i1] - mjds[i2])],
            'sites': list(sites[i1]), 'ccds': list(ccds[i1]),
            'nights': list(nights[i1]),
        })

    return colors


# The query parameters the data themselves depend on. Everything else - the
# resolved name, the plot size, the output mode - only affects the presentation,
# so it must not take part in the cache key below.
LC_PARAMS = [
    'ra', 'dec', 'sr', 'night', 'night1', 'night2', 'site', 'ccd', 'filter',
    'magerr', 'nstars', 'nofiltering', 'sigma',
    'average', 'average_window', 'average_mode',
]

LC_CACHE_TIMEOUT = 600

# Longer light curves are served but not kept: a wide cone may cover a lot of
# stars at once, and an entry costs roughly 150 KiB per thousand points
LC_CACHE_MAX_POINTS = 20000


def lc_query_params(request, **overrides):
    """Stable, hashable form of the parameters the data depend on.

    `overrides` replaces individual ones, which is how a view asks for a variant
    of the light curve the request did not itself describe.
    """
    return tuple((_, overrides.get(_, request.GET.get(_))) for _ in LC_PARAMS)


def cached_lc(request, **overrides):
    """`build_lc` for a request, keeping the result for the other views.

    The same light curve is asked for by the plot and then by the period search,
    so hold on to it instead of querying the database anew every time.
    """
    params = lc_query_params(request, **overrides)
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
    # get_lc returns a list of dicts, one per measurement, keyed by column
    # name (photometry columns plus a few extras pulled from the joined
    # images row).
    data = get_lc(params)

    def col(name, dtype=None):
        return np.array([row[name] for row in data], dtype=dtype)

    if data:
        times = col('time')
        sites = col('site')
        ccds = col('ccd')
        filters = col('filter')
        ras = col('ra')
        decs = col('dec')
        mags = col('mag')
        magerrs = col('magerr')
        flags = col('flags')
        fwhms = col('fwhm')
        stds = col('std')
        nstars = col('nstars')
        color_term = col('color_term')
        zp_std = col('zp_std')
        final_frac = col('final_frac')
        # Object arrays, as either column may be NULL for a measurement whose
        # frame is gone from the archive
        image_ids = col('image_id', dtype=object)
        nights = col('night', dtype=object)
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

    # Optionally combine the measurements of a single visit, which is what the
    # target scripts taking several images in a row produce. Applied last, to the
    # points surviving everything above, so that a spoiled measurement is rejected
    # rather than averaged into a good group.
    averaging = bool(params.get('average'))

    try:
        average_window = float(params.get('average_window') or AVERAGE_WINDOW)
    except ValueError:
        average_window = AVERAGE_WINDOW

    if not np.isfinite(average_window) or average_window <= 0:
        average_window = AVERAGE_WINDOW

    average_mode = params.get('average_mode') or AVERAGE_MODE
    if average_mode not in AVERAGE_MODES:
        average_mode = AVERAGE_MODE

    npoints = None

    if averaging and np.any(idx0):
        averaged = average_lc(
            {
                'times': times[idx0], 'mjds': np.asarray(mjds)[idx0],
                'sites': sites[idx0], 'ccds': ccds[idx0], 'filters': filters[idx0],
                'ras': ras[idx0], 'decs': decs[idx0],
                'mags': mags[idx0], 'magerrs': magerrs[idx0],
                'flags': flags[idx0], 'fwhms': fwhms[idx0],
                'stds': stds[idx0], 'nstars': nstars[idx0],
                'color_term': color_term[idx0],
                'image_ids': image_ids[idx0], 'nights': nights[idx0],
            },
            window=average_window,
            mode=average_mode,
        )

        times, mjds = averaged['times'], averaged['mjds']
        sites, ccds, filters = averaged['sites'], averaged['ccds'], averaged['filters']
        ras, decs = averaged['ras'], averaged['decs']
        mags, magerrs = averaged['mags'], averaged['magerrs']
        flags, fwhms = averaged['flags'], averaged['fwhms']
        stds, nstars, color_term = averaged['stds'], averaged['nstars'], averaged['color_term']
        image_ids, nights = averaged['image_ids'], averaged['nights']
        npoints = averaged['npoints']

        # Everything left has already passed the cuts, and the colours have to
        # follow the regrouped points
        idx0 = np.ones(len(times), dtype=bool)
        cols = np.array([{'B':'blue', 'V':'green', 'R':'red', 'I':'orange', 'z':'magenta'}.get(_, 'black') for _ in filters])

    return {
        'sigma': sigma,
        'npoints': npoints, 'averaging': averaging,
        'average_window': average_window, 'average_mode': average_mode,
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
    # The full dump is of the measurements themselves, so it is taken without the
    # averaging: an averaged point is not a measurement, and the columns
    # describing the frame it was made on would describe several of them at once.
    data = cached_lc(request, average=None) if mode == 'text' else cached_lc(request)

    times, mjds = data['times'], data['mjds']
    sites, ccds, filters, cols = data['sites'], data['ccds'], data['filters'], data['cols']
    ras, decs = data['ras'], data['decs']
    mags, magerrs = data['mags'], data['magerrs']
    flags, fwhms = data['flags'], data['fwhms']
    stds, nstars, color_term = data['stds'], data['nstars'], data['color_term']
    image_ids, nights = data['image_ids'], data['nights']
    idx0, npoints = data['idx0'], data['npoints']

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

    if data['averaging']:
        title += ' - %s over %.0f s' % (
            {'median': 'median', 'clipped': 'clipped mean'}.get(data['average_mode'], 'averaged'),
            data['average_window'])

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
                        'nights': list(nights[idx]),
                        'npoints': [int(_) for _ in npoints[idx]] if npoints is not None else None})

        # Made of the very points drawn above, and so of everything the cuts, the
        # clipping and the averaging left of them
        colors = []
        if request.GET.get('colors'):
            colors = compute_colors(data, displayed_mask(filters, idx0))

        data = {'name': name, 'title': title, 'ra': ra, 'dec': dec, 'sr': sr,
                'lcs': lcs, 'colors': colors}

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
