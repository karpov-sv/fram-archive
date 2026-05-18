from django.http import HttpResponse, FileResponse
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.decorators import permission_required
from django.conf import settings

from django.db.models import Count

import os, sys, io
from urllib.parse import urlencode
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.axes import Axes
from matplotlib import colormaps
from astropy.visualization import simple_norm, ImageNormalize
from astropy.visualization.stretch import HistEqStretch
import numpy as np

import cv2

import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

from skimage.transform import rescale
from io import BytesIO

from astropy.io import fits
from astropy.wcs import WCS

from stdpipe import cutouts, plots, astrometry, photometry, pipeline

from .models import Images
from .utils import image_stats_distinct
from .image_data import (
    find_calibration_image,
    load_image_data,
)

# FRAM modules
from fram.fram import Fram, parse_iso_time, get_night


def get_images(request):
    images = Images.objects.all()

    night = request.GET.get('night')
    if night and night != 'all':
        images = images.filter(night=night)

    night1 = request.GET.get('night1')
    if night1:
        images = images.filter(night__gte=night1)

    night2 = request.GET.get('night2')
    if night2:
        images = images.filter(night__lte=night2)

    site = request.GET.get('site')
    if site and site != 'all':
        images = images.filter(site=site)

    fname = request.GET.get('filter')
    if fname and fname != 'all':
        images = images.filter(filter=fname)

    target = request.GET.get('target')
    if target and target != 'all':
        images = images.filter(target=target)

    object_name = request.GET.get('object')
    if object_name:
        # images = images.filter(keywords__OBJECT=object_name)
        images = images.filter(keywords__OBJECT__istartswith=object_name)

    tname = request.GET.get('type')
    if tname and tname != 'all':
        images = images.filter(type=tname)

    ccd = request.GET.get('ccd')
    if ccd and ccd != 'all':
        images = images.filter(ccd=ccd)

    serial = request.GET.get('serial')
    if serial and serial != 'all':
        images = images.filter(serial=serial)

    binning = request.GET.get('binning')
    if binning and binning != 'all':
        images = images.filter(binning=binning)

    exposure = request.GET.get('exposure')
    if exposure and exposure != 'all':
        images = images.filter(exposure=exposure)

    filename = request.GET.get('filename')
    if filename:
        if '%' in filename:
            # Extended syntax
            images = images.extra(where=["filename like %s"], params=(filename,))
        else:
            images = images.filter(filename__contains=filename)

    return images


@permission_required('auth.can_view_images', raise_exception=True)
def images_list(request):
    context = {}

    images = get_images(request)

    if request.GET.get('ra') and request.GET.get('dec'):
        ra = float(request.GET.get('ra'))
        dec = float(request.GET.get('dec'))
        context['ra'] = ra
        context['dec'] = dec

        sr = float(request.GET.get('sr', 0))
        if sr:
            # Images with centers within given search radius
            images = images.extra(where=["q3c_radial_query(ra, dec, %s, %s, %s)"], params=(ra, dec, sr))
            context['sr'] = sr
        else:
            # Images covering given point
            images = images.extra(where=["q3c_radial_query(ra, dec, %s, %s, radius)"], params=(ra, dec))
            # images = images.extra(select={'dist': "q3c_dist(ra, dec, %s, %s)"}, select_params=(ra,dec))
            images = images.extra(where=["q3c_poly_query(%s, %s, footprint10)"], params=(ra, dec))

    # Possible values for fields
    types = image_stats_distinct('type')
    context['types'] = types

    sites = image_stats_distinct('site')
    context['sites'] = sites

    ccds = image_stats_distinct('ccd')
    filters = image_stats_distinct('filter')
    context['ccds'] = ccds

    context['filters'] = filters

    sort = request.GET.get('sort')
    if sort:
        images = images.order_by(*(sort.split(',')))
    else:
        images = images.order_by('-time')

    context['images'] = images

    if images.count() == 1:
        return redirect('image_details', id=images.first().id)

    return TemplateResponse(request, 'images.html', context=context)


@permission_required('auth.can_view_images', raise_exception=True)
def images_cutouts(request):
    context = {}

    images = get_images(request)

    ra = float(request.GET.get('ra', 0))
    dec = float(request.GET.get('dec', 0))
    sr = float(request.GET.get('sr', 0.1))
    maxdist = float(request.GET.get('maxdist', 0.0))
    context['ra'] = ra
    context['dec'] = dec
    context['sr'] = sr
    context['maxdist'] = maxdist

    # Images containing given point
    images = images.extra(where=["q3c_radial_query(ra, dec, %s, %s, radius)"], params=(ra, dec))
    images = images.extra(select={'dist': "q3c_dist(ra, dec, %s, %s)"}, select_params=(ra,dec))
    images = images.extra(where=["q3c_poly_query(%s, %s, footprint10)"], params=(ra, dec))

    if maxdist > 0:
        images = images.extra(where=["q3c_dist(ra, dec, %s, %s) < %s"], params=(ra, dec, maxdist))

    # Possible values for fields
    sites = image_stats_distinct('site')
    context['sites'] = sites

    ccds = image_stats_distinct('ccd')
    context['ccds'] = ccds

    filters = image_stats_distinct('filter')
    context['filters'] = filters

    sort = request.GET.get('sort')
    if sort:
        images = images.order_by(*(sort.split(',')))
    else:
        images = images.order_by('-time')

    context['images'] = images

    context['cutouts'] = True

    return TemplateResponse(request, 'images_cutouts.html', context=context)


@permission_required('auth.can_view_images', raise_exception=True)
def image_details(request, id=0):
    context = {}

    image = Images.objects.get(id=id)
    context['image'] = image

    # Calibrations
    if image.type not in ['masterdark', 'masterflat', 'bias', 'dcurrent', 'dark', 'zero']:
        context['dark'] = find_calibration_image(image, 'masterdark')

        if context['dark'] is None:
            context['bias'] = find_calibration_image(image, 'bias')
            context['dcurrent'] = find_calibration_image(image, 'dcurrent')

        if image.type not in ['flat']:
            context['flat'] = find_calibration_image(image, 'masterflat')

    try:
        # Try to read original FITS keywords with comments
        filename = os.path.join(settings.BASE_DIR, image.filename)
        header = fits.getheader(filename, -1)

        # ignored_keywords = ['COMMENT', 'SIMPLE', 'BZERO', 'BSCALE', 'EXTEND', 'HISTORY']
        # keywords = [{'key':k, 'value':repr(header[k]), 'comment':header.comments[k]} for k in header.keys() if k not in ignored_keywords]

        # context['keywords'] = keywords
        context['header'] = header
    except:
        pass

    return TemplateResponse(request, 'image.html', context=context)


def image_response(data, qq=[2.5, 99.75], stretch='linear', cmap='Blues_r', quality=75):
    limits = np.percentile(data[np.isfinite(data)], qq)

    if stretch == 'histeq':
        norm = ImageNormalize(
            stretch=HistEqStretch(data),
            vmin=limits[0],
            vmax=limits[1],
        )
    elif stretch != 'linear':
        norm = simple_norm(
            data,
            stretch,
            min_cut=limits[0],
            max_cut=limits[1],
            power=2,
        )
    else:
        norm = None

    if norm is None:
        data = (data - limits[0]) / (limits[1] - limits[0])
    else:
        data = norm(data)

    data = np.clip(data, 0.0, 1.0)

    cmap = colormaps[cmap]
    data = cmap(data) # RGBA

    data = (255 * data).astype(np.uint8)

    # OpenCV expects BGRA
    data = cv2.cvtColor(data, cv2.COLOR_RGBA2BGRA)

    data = cv2.flip(data, 0)

    success, buf = cv2.imencode(
        ".jpg",
        data,
        [cv2.IMWRITE_JPEG_QUALITY, int(quality)]
    )
    if not success:
        return HttpResponse(status=500)

    return HttpResponse(
        buf.tobytes(),
        content_type="image/jpeg"
    )


@cache_page(3600)
@permission_required('auth.can_view_images', raise_exception=True)
def image_preview(request, id=0, size=0):
    image = Images.objects.get(id=id)

    if 'size' in request.GET:
        size = int(request.GET.get('size', 0))

    loaded = load_image_data(
        image,
        mode="raw" if 'raw' in request.GET else "preview",
    )
    data = loaded.data

    if int(request.GET.get('grid', 0)):
        show_grid = True
    else:
        show_grid = False

    zoom = int(request.GET.get('zoom', 1))

    if show_grid is False:
        # Fast OpenCV-based image display
        if zoom > 1:
            x0,width = data.shape[1]/2, data.shape[1]
            y0,height = data.shape[0]/2, data.shape[0]

            x0 += float(request.GET.get('dx', 0)) * width/4
            y0 += float(request.GET.get('dy', 0)) * height/4

            half_width = 0.5 * width / zoom
            half_height = 0.5 * height / zoom

            x1, x2 = int(x0 - half_width), int(x0 + half_width)
            y1, y2 = int(y0 - half_height), int(y0 + half_height)

            target_width = x2 - x1
            target_height = y2 - y1

            padded = np.zeros((target_height, target_width), dtype=np.double)

            src_x1 = max(0, x1)
            src_y1 = max(0, y1)
            src_x2 = min(width, x2)
            src_y2 = min(height, y2)

            if src_x2 > src_x1 and src_y2 > src_y1:
                dst_x1 = src_x1 - x1
                dst_y1 = src_y1 - y1
                dst_x2 = dst_x1 + (src_x2 - src_x1)
                dst_y2 = dst_y1 + (src_y2 - src_y1)

                padded += np.nanmedian(data[src_y1:src_y2, src_x1:src_x2])
                padded[dst_y1:dst_y2, dst_x1:dst_x2] = data[src_y1:src_y2, src_x1:src_x2]

            data = padded

        if size:
            data = cv2.resize(data, [int(size), int(size * data.shape[0]/data.shape[1])], interpolation=cv2.INTER_AREA)

        return image_response(
            data,
            stretch=request.GET.get('stretch', 'linear'),
            qq=[float(request.GET.get('qmin', 0.5)), float(request.GET.get('qmax', 99.5))],
            cmap=request.GET.get('cmap', 'Blues_r'),
            quality=int(request.GET.get('quality', 75))
        )

    # Default STDPipe based imshow
    figsize = [data.shape[1]*zoom, data.shape[0]*zoom]

    if zoom > 1:
        x0,dx0 = data.shape[1]/2, data.shape[1]
        y0,dy0 = data.shape[0]/2, data.shape[0]

        x0 += float(request.GET.get('dx', 0)) * dx0/4
        y0 += float(request.GET.get('dy', 0)) * dy0/4

        xlim = [x0 - 0.5*dx0/zoom, x0 + 0.5*dx0/zoom]
        ylim = [y0 - 0.5*dy0/zoom, y0 + 0.5*dy0/zoom]
    else:
        xlim = [0, data.shape[1]-1]
        ylim = [0, data.shape[0]-1]

    if size and figsize[0] != size:
        figsize[1] = size*figsize[1]/figsize[0]
        figsize[0] = size

    fig = Figure(dpi=72, figsize=(figsize[0]/72, figsize[1]/72))
    if show_grid:
        dx = 40/figsize[0]
        dy = 20/figsize[1]
        ax = Axes(fig, [dx, dy, 0.99 - 2*dx, 0.99 - dy])
        ax.grid(color='white', alpha=0.3)
    else:
        # No axes, just the image
        ax = Axes(fig, [0., 0., 1., 1.])

    fig.add_axes(ax)

    plots.imshow(
        data, ax=ax, mask=None,
        show_axis=True if show_grid else False,
        show_colorbar=True if show_grid else False,
        origin='lower',
        interpolation='nearest' if data.shape[1]/zoom < 0.5*size else 'bicubic',
        cmap=request.GET.get('cmap', 'Blues_r'),
        stretch=request.GET.get('stretch', 'linear'),
        qq=[float(request.GET.get('qmin', 0.5)), float(request.GET.get('qmax', 99.5))],
        r0=float(request.GET.get('r0', 0)),
        # Use fast (approximate) image display
        max_plot_size=1024, xlim=xlim, ylim=ylim, fast=True
    )

    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)

    fmt = 'jpeg'
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, pil_kwargs={'quality':int(request.GET.get('quality', 75))})

    return HttpResponse(buf.getvalue(), content_type='image/%s' % fmt)


@permission_required('auth.can_view_images', raise_exception=True)
def image_download(request, id, raw=True):
    image = Images.objects.get(id=id)

    filename = image.filename
    filename = os.path.join(settings.BASE_DIR, filename)

    if raw or image.type in ['masterdark', 'masterflat', 'dcurrent', 'bias']:
        response = FileResponse(open(filename, "rb"), content_type='application/octet-stream')
        response['Content-Disposition'] = 'attachment; filename='+os.path.split(filename)[-1]
        response['Content-Length'] = os.path.getsize(filename)
        return response
    else:
        loaded = load_image_data(
            image,
            mode="processed",
        )
        data = loaded.data
        header = loaded.header

        s = BytesIO()
        fits.writeto(s, data, header)

        response = HttpResponse(s.getvalue(), content_type='application/octet-stream')
        response['Content-Disposition'] = 'attachment; filename=' + os.path.split(filename)[-1] + '.processed.fits'
        response['Content-Length'] = len(s.getvalue())
        return response


@cache_page(3600)
@permission_required('auth.can_view_images', raise_exception=True)
def images_nights(request, night=None):
    sites = image_stats_distinct('site')
    object_query = (request.GET.get('object') or '').strip()

    if night is not None or object_query:
        images = Images.objects.filter(night=night) if night is not None else Images.objects.all()

        object_target = None
        if object_query:
            try:
                object_target = int(object_query)
            except ValueError:
                images = images.filter(keywords__OBJECT__istartswith=object_query)
            else:
                images = images.filter(target=object_target)

        site = request.GET.get('site')
        if site and site != 'all':
            images = images.filter(site=site)

        ccds = list(images.order_by('ccd').distinct('ccd').values('ccd'))
        ccd = request.GET.get('ccd')
        if ccd and ccd != 'all':
            images = images.filter(ccd=ccd)

        # Full list of known filters for dynamic columns
        filters = image_stats_distinct('filter')
        preferred_filters = ['n', 'b', 'v', 'r', 'i', 'z', 'df']
        preferred_index = {name: i for i, name in enumerate(preferred_filters)}
        table_filters = sorted(
            [f['filter'] for f in filters if f.get('filter') is not None],
            key=lambda value: (
                preferred_index.get(str(value).lower(), len(preferred_filters)),
                str(value).lower(),
            ),
        )

        object_mode = bool(object_query and night is None)
        grouped_fields = ['site', 'ccd', 'target', 'keywords__OBJECT', 'filter']
        grouped_order = ['site', 'target', 'ccd', 'keywords__OBJECT', 'filter']
        if object_mode:
            grouped_fields.insert(0, 'night')
            grouped_order.insert(0, '-night')

        grouped = images.values(*grouped_fields).annotate(count=Count('id')).order_by(*grouped_order)

        base_params = {}
        if night is not None:
            base_params['night'] = night
        elif object_query:
            if object_target is not None:
                base_params['target'] = object_target
            else:
                base_params['object'] = object_query

        night_rows = {}
        for row in grouped:
            row_night = row.get('night')
            key = (row_night, row['site'], row['ccd'], row['target'], row['keywords__OBJECT']) if object_mode else (row['site'], row['ccd'], row['target'], row['keywords__OBJECT'])
            if key not in night_rows:
                row_params = base_params.copy()
                if row_night is not None:
                    row_params['night'] = row_night

                site_params = row_params.copy()
                if row['site'] is not None:
                    site_params['site'] = row['site']

                ccd_params = site_params.copy()
                if row['ccd'] is not None:
                    ccd_params['ccd'] = row['ccd']

                target_params = ccd_params.copy()
                if row['target'] is not None:
                    target_params['target'] = row['target']

                night_rows[key] = {
                    'night': row_night,
                    'site': row['site'],
                    'ccd': row['ccd'],
                    'target': row['target'],
                    'object': row['keywords__OBJECT'],
                    'section': row_night if object_mode else row['site'],
                    'site_query': urlencode(site_params),
                    'ccd_query': urlencode(ccd_params),
                    'target_query': urlencode(target_params),
                    'filter_counts': {},
                    'filter_queries': {},
                }

            params = base_params.copy()
            if row_night is not None:
                params['night'] = row_night
            if row['site'] is not None:
                params['site'] = row['site']
            if row['ccd'] is not None:
                params['ccd'] = row['ccd']
            if row['target'] is not None:
                params['target'] = row['target']
            if row['filter'] is not None:
                params['filter'] = row['filter']

            night_rows[key]['filter_counts'][row['filter']] = row['count']
            night_rows[key]['filter_queries'][row['filter']] = urlencode(params)

        context = {
            'night': night,
            'object_query': object_query,
            'single_night': True,
            'object_mode': object_mode,
            'night_rows': list(night_rows.values()),
            'sites': sites,
            'ccds': ccds,
            'table_filters': table_filters,
        }

    else:
        nights = Images.objects.values('night', 'site').annotate(count=Count('id')).order_by('-night', 'site')
        site = request.GET.get('site')
        if site and site != 'all':
            nights = nights.filter(site=site)

        table_sites = [site] if site and site != 'all' else [s['site'] for s in sites]

        grouped = {}
        for row in nights:
            row_night = row['night']
            if row_night not in grouped:
                grouped[row_night] = {'night': row_night, 'counts': {}}
            grouped[row_night]['counts'][row['site']] = row['count']

        context = {
            'nights': list(grouped.values()),
            'sites': sites,
            'table_sites': table_sites,
            'object_query': object_query,
            'single_night': False,
            'object_mode': False,
        }

    return TemplateResponse(request, 'nights.html', context=context)


@cache_page(3600)
@permission_required('auth.can_analyze_images', raise_exception=True)
def image_analysis(request, id=0, mode='fwhm'):
    image = Images.objects.get(id=id)
    filename = image.filename
    filename = os.path.join(settings.BASE_DIR, filename)

    loaded = load_image_data(
        image,
        mode="analysis",
    )
    data = loaded.data
    header = loaded.header
    mask = loaded.mask

    # Actual analysis

    if mode == 'zero':
        fig = Figure(facecolor='white', dpi=72, figsize=(16,8), tight_layout=True)
    else:
        fig = Figure(facecolor='white', dpi=72, figsize=(14,12), tight_layout=True)

    if mode == 'bg':
        bg, bg_rms = photometry.get_background(
            data,
            method='sep',
            size=128,
            get_rms=True,
        )

        ax = fig.add_subplot(111)
        plots.imshow(bg, ax=ax, origin='lower')
        ax.set_title('%s - %s %s %s %s - bg mean %.2f median %.2f rms %.2f' % (os.path.split(filename)[-1], image.site, image.ccd, image.filter, str(image.exposure), np.nanmean(bg), np.nanmedian(bg), np.nanmedian(bg_rms)))

    elif mode == 'fwhm':
        # Detect objects; the returned table now carries both `fwhm` and
        # `flux_radius` columns (stdpipe >= 0.3).
        obj = photometry.get_objects_sep(data, fwhm=True, verbose=False)

        # Robust global FWHM via stdpipe's mode-based estimator. Internally
        # prefers 2*flux_radius and applies S/N + ellipticity + flag cuts.
        fwhm_global = float(photometry.estimate_fwhm_from_objects(
            obj,
            snr_min=10.0,
            max_ellipticity=0.3,
            use_flags=True,
            image_shape=data.shape,
            verbose=False,
        ))

        # Half-flux diameter (2*flux_radius) is markedly more stable across
        # the frame than SEP's Gaussian-core FWHM and is what the upstream
        # estimator prefers; fall back only if the column is missing.
        if 'flux_radius' in obj.colnames:
            values = 2.0 * np.asarray(obj['flux_radius'], dtype=float)
            label = 'half-flux diameter'
        else:
            values = np.asarray(obj['fwhm'], dtype=float)
            label = 'FWHM'

        # Quality mask mirroring estimate_fwhm_from_objects: unflagged,
        # round-ish, finite S/N, and within the plausible FWHM range.
        good = np.asarray(obj['flags']) <= 0x01
        a = np.asarray(obj['a'], dtype=float)
        b = np.asarray(obj['b'], dtype=float)
        with np.errstate(invalid='ignore'):
            good &= (a > 0) & ((1.0 - b / a) < 0.3)
        magerr = np.asarray(obj['magerr'], dtype=float)
        good &= np.isfinite(magerr) & (magerr > 0) & (magerr < 0.1)
        good &= np.isfinite(values) & (values >= 1.0) & (values < 20.0)

        ax = fig.add_subplot(111)
        plots.binned_map(obj['x'][good], obj['y'][good], values[good],
                         bins=16, statistic='median', ax=ax)
        ax.set_title(
            '%s - %s %s %s %s - %s median %.2f mean %.2f robust %.2f pix (n=%d)' % (
                os.path.split(filename)[-1], image.site, image.ccd,
                image.filter, str(image.exposure), label,
                np.nanmedian(values[good]), np.nanmean(values[good]),
                fwhm_global, int(good.sum()),
            )
        )

    elif mode == 'wcs':
        wcs = WCS(header)

        if wcs is not None and wcs.is_celestial:
            # Detect objects
            obj = photometry.get_objects_sep(data, fwhm=True, wcs=wcs, verbose=False)

            pixscale = astrometry.get_pixscale(wcs=wcs)

            # Get stars from catalogue
            fram = Fram()
            ra0, dec0, sr0 = astrometry.get_frame_center(wcs=wcs, shape=data.shape)
            if ra0 is not None and sr0 is not None:
                if sr0 < 3.0:
                    cat = fram.get_stars(ra0, dec0, sr0, limit=100000, catalog='gaiadr3syn', extra=['r < 15'])
                else:
                    cat = fram.get_stars(ra0, dec0, sr0, limit=100000, catalog='gaiadr3syn', extra=['r < 10'])

                # Robust global FWHM (mode-based, with S/N + ellipticity cuts)
                # drives the catalogue match radius. Much less sensitive to
                # galaxies/blends than a plain median over all detections.
                fwhm_global = float(photometry.estimate_fwhm_from_objects(
                    obj,
                    snr_min=10.0,
                    max_ellipticity=0.3,
                    use_flags=True,
                    image_shape=data.shape,
                    verbose=False,
                ))
                if not np.isfinite(fwhm_global):
                    fwhm_global = np.nanmedian(obj['fwhm'])

                sr = 2.0 * pixscale * fwhm_global

                # Match stars
                filter_key = (header.get('FILTER') or '').strip().upper()
                if filter_key == 'N':
                    filter_key = 'R'
                if filter_key == 'Z':
                    filter_key = 'z'

                if filter_key in cat.colnames:
                    mag_err_col = f"{filter_key}err"
                    if mag_err_col not in cat.colnames:
                        mag_err_col = None

                    match = pipeline.calibrate_photometry(
                        obj,
                        cat,
                        sr=sr,
                        order=4,
                        sn=10,
                        cat_col_mag=filter_key,
                        cat_col_mag_err=mag_err_col,
                        cat_col_mag1='B',
                        cat_col_mag2='V',
                        cat_col_ra='ra',
                        cat_col_dec='dec',
                        # accept_flags=0x01, max_intrinsic_rms=0.02,
                        verbose=False,
                    )

                    if match:
                        ax = fig.add_subplot(111)
                        plots.plot_photometric_match(match, ax=ax, mode='dist', show_masked=False)

                # oidx, cidx, dist = astrometry.spherical_match(obj['ra'], obj['dec'], cat['ra'], cat['dec'], sr=sr)
                # if len(dist):
                #     order = np.argsort(dist)
                #     oidx, cidx, dist = oidx[order], cidx[order], dist[order]
                #     _, uniq_idx = np.unique(oidx, return_index=True)
                #     oidx, cidx, dist = oidx[uniq_idx], cidx[uniq_idx], dist[uniq_idx]

                # dist = dist * 3600

                # idx = obj['flags'][oidx] == 0

                # ax = fig.add_subplot(111)
                # plots.binned_map(
                #     obj['x'][oidx][idx], obj['y'][oidx][idx], dist[idx],
                #     show_dots=True,
                #     bins=16,
                #     statistic='median',
                #     ax=ax
                # )

                # ax.set_title('%s - %s %s %s - displacement mean %.1f median %.1f arcsec pixel %.1f arcsec' % (os.path.split(filename)[-1], image.site, image.ccd, image.filter, np.nanmean(dist[idx]), np.nanmedian(dist[idx]), pixscale*3600))

    elif mode == 'filters':
        wcs = WCS(header)

        if wcs is not None and wcs.is_celestial:
            pixscale = astrometry.get_pixscale(wcs=wcs)

            if request.GET.get('aper'):
                aper = float(request.GET.get('aper'))
                obj = photometry.get_objects_sep(data, wcs=wcs, aper=aper, fwhm=False, verbose=False, mask=mask)
            else:
                obj = photometry.get_objects_sep(data, wcs=wcs, aper=1, fwhm=True, verbose=False, mask=mask)

            # Get stars from catalogue
            fram = Fram()
            ra0, dec0, sr0 = astrometry.get_frame_center(wcs=wcs, shape=data.shape)
            if ra0 is not None and sr0 is not None:
                if 'WF' not in header.get('CCD_NAME', ''):
                    cat = fram.get_stars(ra0, dec0, sr0, limit=100000, catalog='gaiadr3syn', extra=['r < 15'])
                else:
                    cat = fram.get_stars(ra0, dec0, sr0, limit=100000, catalog='gaiadr3syn', extra=['r > 6', 'r < 10'])

                sr = pixscale * np.nanmedian(obj['fwhm'])

                for i,fname in enumerate(['B', 'V', 'R', 'I']):
                    if fname not in cat.colnames:
                        continue

                    mag_err_col = f"{fname}err"
                    if mag_err_col not in cat.colnames:
                        mag_err_col = None

                    ax = fig.add_subplot(2, 2, i+1)
                    match = pipeline.calibrate_photometry(
                        obj,
                        cat,
                        sr=sr,
                        order=4,
                        sn=10,
                        cat_col_mag=fname,
                        cat_col_mag_err=mag_err_col,
                        cat_col_mag1='B',
                        cat_col_mag2='V',
                        cat_col_ra='ra',
                        cat_col_dec='dec',
                        # use_color=False,
                        accept_flags=0x01,
                        verbose=False,
                    )
                    if match:
                        plots.plot_photometric_match(match, ax=ax, mode='color', show_masked=False)
                        title = ax.get_title()
                        ax.set_title(f"{fname} {title}".strip())

    elif mode == 'zero':
        wcs = WCS(header)

        if wcs is not None and wcs.is_celestial:
            pixscale = astrometry.get_pixscale(wcs=wcs)

            if request.GET.get('aper'):
                aper = float(request.GET.get('aper'))
                obj = photometry.get_objects_sep(data, wcs=wcs, aper=aper, fwhm=False, verbose=False, mask=mask)
            else:
                obj = photometry.get_objects_sep(data, wcs=wcs, aper=1, fwhm=True, verbose=False, mask=mask)

            aper = obj.meta.get('aper')

            # Get stars from catalogue
            fram = Fram()
            ra0, dec0, sr0 = astrometry.get_frame_center(wcs=wcs, shape=data.shape)
            if ra0 is not None and sr0 is not None:
                if 'WF' not in header.get('CCD_NAME', ''):
                    cat = fram.get_stars(ra0, dec0, sr0, limit=100000, catalog='gaiadr3syn', extra=['r < 15'])
                else:
                    cat = fram.get_stars(ra0, dec0, sr0, limit=100000, catalog='gaiadr3syn', extra=['r > 6', 'r < 10'])

                sr = 0.5 * pixscale * np.nanmedian(obj['fwhm'])

                filter_key = (header.get('FILTER') or '').strip().upper()
                if filter_key == 'N':
                    filter_key = 'R'
                if filter_key == 'Z':
                    filter_key = 'z'

                if filter_key in cat.colnames:
                    mag_err_col = f"{filter_key}err"
                    if mag_err_col not in cat.colnames:
                        mag_err_col = None

                    match = pipeline.calibrate_photometry(
                        obj,
                        cat,
                        sr=sr,
                        order=4,
                        sn=10,
                        cat_col_mag=filter_key,
                        cat_col_mag_err=mag_err_col,
                        cat_col_mag1='B',
                        cat_col_mag2='V',
                        cat_col_ra='ra',
                        cat_col_dec='dec',
                        accept_flags=0x01, max_intrinsic_rms=0.02,
                        verbose=False,
                    )

                    if match:
                        ax = fig.add_subplot(321)
                        plots.plot_photometric_match(match, ax=ax, mode='mag', show_masked=False)

                        ax = fig.add_subplot(323)
                        plots.plot_photometric_match(match, ax=ax, mode='color', show_masked=False)

                        ax = fig.add_subplot(325)
                        ax.hist(match['cmag'], bins=100)
                        ax.set_xlabel('Catalogue mag')

                        ax = fig.add_subplot(122)
                        plots.plot_photometric_match(match, ax=ax, mode='zero', bins=8, aspect='equal')
                        title = f"filter {filter_key}"
                        if aper:
                            title += f" aper {aper:.1f}"
                        ax.set_title(title)

    canvas = FigureCanvas(fig)

    response = HttpResponse(content_type='image/jpeg')
    canvas.print_jpg(response)

    return response


@cache_page(3600)
@permission_required('auth.can_view_images', raise_exception=True)
def image_cutout(request, id=0, size=0, mode='view'):
    image = Images.objects.get(id=id)
    filename = image.filename
    filename = os.path.join(settings.BASE_DIR, filename)

    loaded = load_image_data(
        image,
        mode="cutout",
    )
    data = loaded.data
    header = loaded.header

    ra,dec,sr = float(request.GET.get('ra')), float(request.GET.get('dec')), float(request.GET.get('sr'))

    wcs = WCS(header)
    x0,y0 = wcs.all_world2pix(ra, dec, sr)
    r0 = sr/np.hypot(wcs.pixel_scale_matrix[0,0], wcs.pixel_scale_matrix[0,1])

    # crop,cropheader = utils.crop_image(data, x0, y0, r0, header)
    crop,cropheader = cutouts.crop_image_centered(data, x0, y0, r0, header=header)

    if mode == 'download':
        s = BytesIO()
        fits.writeto(s, crop, cropheader)

        response = HttpResponse(s.getvalue(), content_type='application/octet-stream')
        response['Content-Disposition'] = 'attachment; filename=crop_'+os.path.split(filename)[-1]
        response['Content-Length'] = len(s.getvalue())
        return response

    if size:
        if size > crop.shape[1]:
            crop = rescale(crop, size/crop.shape[1], mode='reflect', anti_aliasing=False, order=0)
        else:
            crop = rescale(crop, size/crop.shape[1], mode='reflect', anti_aliasing=True)

    response = image_response(
        crop,
        qq=[2.5, float(request.GET.get('qq', 99.75))],
        cmap=request.GET.get('cmap', 'Blues_r'),
        quality=int(request.GET.get('quality', 75))
    )

    return response
