from django.http import HttpResponse, FileResponse
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.decorators import permission_required
from django.conf import settings

from django.db.models import Count

import os, sys, posixpath, io
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

from .models import Images, Calibrations
from .utils import db_query, memoize

# FRAM modules
from fram import calibrate
from fram.fram import Fram, parse_iso_time, get_night


@memoize(timeout=3600, make_key=lambda image, type='masterdark', **kwargs: f"calib:{image.id}:{type}")
def find_calibration_image(image, type='masterdark', night=None, site=None, ccd=None, serial=None, exposure=None, cropped_width=None, cropped_height=None, filter=None, binning=None):
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

#    print(type, image.site, image.ccd, image.serial, image.binning, image.keywords['NAXIS1'], image.keywords['NAXIS2'], image.filter, image.exposure)

    calibs1 = calibs.filter(night__lte=image.night).order_by('-night')
    if calibs1.first():
        return calibs1.first()
    else:
        # No frames earlier than the date, let's look for a later one!
        calibs1 = calibs.filter(night__gte=image.night).order_by('night')
        return calibs1.first()


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
        sr = float(request.GET.get('sr', 0))
        context['ra'] = ra
        context['dec'] = dec
        context['sr'] = sr

        # Images with centers within given search radius
        images = images.extra(where=["q3c_radial_query(ra, dec, %s, %s, %s)"], params=(ra, dec, sr))

    # Possible values for fields
    # types = images.distinct('type').values('type')
    types = db_query("select fast_distinct(%s, %s) as type", ('images', 'type'))
    context['types'] = types

    # sites = images.distinct('site').values('site')
    sites = db_query("select fast_distinct(%s, %s) as site", ('images', 'site'))
    context['sites'] = sites

    # ccds = images.distinct('ccd').values('ccd')
    ccds = db_query("select fast_distinct(%s, %s) as ccd", ('images', 'ccd'))
    filters = db_query("select fast_distinct(%s, %s) as filter", ('images', 'filter'))
    context['ccds'] = ccds

    # filters = images.distinct('filter').values('filter')
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
    # sites = images.distinct('site').values('site')
    sites = db_query("select fast_distinct(%s, %s) as site", ('images', 'site'))
    context['sites'] = sites

    # ccds = images.distinct('ccd').values('ccd')
    ccds = db_query("select fast_distinct(%s, %s) as ccd", ('images', 'ccd'))
    context['ccds'] = ccds

    # filters = images.distinct('filter').values('filter')
    filters = db_query("select fast_distinct(%s, %s) as filter", ('images', 'filter'))
    context['filters'] = filters

    sort = request.GET.get('sort')
    if sort:
        images = images.order_by(*(sort.split(',')))
    else:
        images = images.order_by('-time')

    context['images'] = images

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
        filename = posixpath.join(settings.BASE_DIR, image.filename)
        header = fits.getheader(filename, -1)

        # ignored_keywords = ['COMMENT', 'SIMPLE', 'BZERO', 'BSCALE', 'EXTEND', 'HISTORY']
        # keywords = [{'key':k, 'value':repr(header[k]), 'comment':header.comments[k]} for k in header.keys() if k not in ignored_keywords]

        # context['keywords'] = keywords
        context['header'] = header
    except:
        pass

    return TemplateResponse(request, 'image.html', context=context)


def image_response(data, qq=[2.5, 99.75], stretch=None, cmap='Blues_r', quality=75):
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
    filename = image.filename
    filename = posixpath.join(settings.BASE_DIR, filename)

    data = fits.getdata(filename, -1).astype(np.double)
    header = fits.getheader(filename, -1)

    if 'size' in request.GET:
        size = int(request.GET.get('size', 0))

    if not 'raw' in request.GET:
        if image.type not in ['masterdark', 'masterflat', 'bias', 'dcurrent']:
            dark = None

            if image.type not in ['dark', 'zero']:
                cdark = find_calibration_image(image, 'masterdark')
                if cdark is not None:
                    dark = fits.getdata(cdark.filename, -1)
                else:
                    cbias,cdc = find_calibration_image(image, 'bias'), find_calibration_image(image, 'dcurrent')
                    if cbias is not None and cdc is not None:
                        bias = fits.getdata(cbias.filename, -1)
                        dc = fits.getdata(cdc.filename, -1)

                        dark = bias + image.exposure*dc

            if dark is not None:
                data,header = calibrate.calibrate(data, header, dark=dark) # Subtract dark and linearize

                if image.type not in ['flat1']:
                    cflat = find_calibration_image(image, 'masterflat')
                    if cflat is not None:
                        flat = fits.getdata(cflat.filename, -1)
                        data *= np.median(flat)/flat
            else:
                data,header = calibrate.crop_overscans(data, header)
    else:
        data,header = calibrate.crop_overscans(data, header, subtract=False)

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
    filename = posixpath.join(settings.BASE_DIR, filename)

    if raw or image.type in ['masterdark', 'masterflat', 'dcurrent', 'bias']:
        response = FileResponse(open(filename, "rb"), content_type='application/octet-stream')
        response['Content-Disposition'] = 'attachment; filename='+os.path.split(filename)[-1]
        response['Content-Length'] = os.path.getsize(filename)
        return response
    else:
        data = fits.getdata(filename, -1).astype(np.double)
        header = fits.getheader(filename, -1)

        if image.type not in ['masterdark', 'masterflat', 'dcurrent', 'bias']:
            dark = None

            if image.type not in ['dark', 'zero']:
                cdark = find_calibration_image(image, 'masterdark')
                if cdark is not None:
                    dark = fits.getdata(cdark.filename, -1)
                else:
                    cbias,cdc = find_calibration_image(image, 'bias'), find_calibration_image(image, 'dcurrent')
                    if cbias is not None and cdc is not None:
                        bias = fits.getdata(cbias.filename, -1)
                        dc = fits.getdata(cdc.filename, -1)

                        dark = bias + image.exposure*dc

            if dark is not None:
                data,header = calibrate.calibrate(data, header, dark=dark) # Subtract dark and linearize

                if image.type not in ['flat']:
                    cflat = find_calibration_image(image, 'masterflat')
                    if cflat is not None:
                        flat = fits.getdata(cflat.filename, -1)
                        data *= np.median(flat)/flat
            else:
                data,header = calibrate.crop_overscans(data, header)

        s = BytesIO()
        fits.writeto(s, data, header)

        response = HttpResponse(s.getvalue(), content_type='application/octet-stream')
        response['Content-Disposition'] = 'attachment; filename=' + os.path.split(filename)[-1] + '.processed.fits'
        response['Content-Length'] = len(s.getvalue())
        return response


@cache_page(3600)
@permission_required('auth.can_view_images', raise_exception=True)
def images_nights(request, night=None):
    # sites = list(Images.objects.order_by('site').distinct('site').values('site'))
    sites = db_query("select fast_distinct(%s, %s) as site", ('images', 'site'))

    if night is not None:
        images = Images.objects.filter(night=night)

        site = request.GET.get('site')
        if site and site != 'all':
            images = images.filter(site=site)

        ccds = list(images.order_by('ccd').distinct('ccd').values('ccd'))
        ccd = request.GET.get('ccd')
        if ccd and ccd != 'all':
            images = images.filter(ccd=ccd)

        # Full list of known filters for dynamic columns
        filters = db_query("select fast_distinct(%s, %s) as filter", ('images', 'filter'))
        preferred_filters = ['n', 'b', 'v', 'r', 'i', 'z', 'df']
        preferred_index = {name: i for i, name in enumerate(preferred_filters)}
        table_filters = sorted(
            [f['filter'] for f in filters if f.get('filter') is not None],
            key=lambda value: (
                preferred_index.get(str(value).lower(), len(preferred_filters)),
                str(value).lower(),
            ),
        )

        grouped = images.values('site', 'ccd', 'target', 'keywords__OBJECT', 'filter').annotate(count=Count('id')).order_by('site', 'target', 'ccd', 'keywords__OBJECT', 'filter')

        night_rows = {}
        for row in grouped:
            key = (row['site'], row['ccd'], row['target'], row['keywords__OBJECT'])
            if key not in night_rows:
                night_rows[key] = {
                    'site': row['site'],
                    'ccd': row['ccd'],
                    'target': row['target'],
                    'object': row['keywords__OBJECT'],
                    'filter_counts': {},
                    'filter_queries': {},
                }

            params = {'night': night}
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
            'single_night': True,
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
            night = row['night']
            if night not in grouped:
                grouped[night] = {'night': night, 'counts': {}}
            grouped[night]['counts'][row['site']] = row['count']

        context = {
            'nights': list(grouped.values()),
            'sites': sites,
            'table_sites': table_sites,
            'single_night': False,
        }

    return TemplateResponse(request, 'nights.html', context=context)


@cache_page(3600)
@permission_required('auth.can_analyze_images', raise_exception=True)
def image_analysis(request, id=0, mode='fwhm'):
    image = Images.objects.get(id=id)
    filename = image.filename
    filename = posixpath.join(settings.BASE_DIR, filename)

    data = fits.getdata(filename, -1).astype(np.double)
    header = fits.getheader(filename, -1)

    dark = None
    flat = None

    # Clean up the header from COMMENT and HISTORY keywords that may break things
    header.remove('COMMENT', remove_all=True, ignore_missing=True)
    header.remove('HISTORY', remove_all=True, ignore_missing=True)

    # Preprocess the image
    if image.type not in ['masterdark', 'masterflat', 'dcurrent', 'bias']:
        if image.type not in ['dark', 'zero']:
            cdark = find_calibration_image(image, 'masterdark')
            if cdark is not None:
                dark = fits.getdata(cdark.filename, -1)
            else:
                cbias,cdc = find_calibration_image(image, 'bias'), find_calibration_image(image, 'dcurrent')
                if cbias is not None and cdc is not None:
                    bias = fits.getdata(cbias.filename, -1)
                    dc = fits.getdata(cdc.filename, -1)

                    dark = bias + image.exposure*dc

        if dark is not None:
            data,header = calibrate.calibrate(data, header, dark=dark) # Subtract dark and linearize

            if image.type not in ['flat']:
                cflat = find_calibration_image(image, 'masterflat')
                if cflat is not None:
                    flat = fits.getdata(cflat.filename, -1)
                    data *= np.median(flat)/flat
        else:
            data,header = calibrate.crop_overscans(data, header)

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
        ax.set_title('%s - %s %s %s %s - bg mean %.2f median %.2f rms %.2f' % (posixpath.split(filename)[-1], image.site, image.ccd, image.filter, str(image.exposure), np.nanmean(bg), np.nanmedian(bg), np.nanmedian(bg_rms)))

    elif mode == 'fwhm':
        # Detect objects and plot their FWHM
        obj = photometry.get_objects_sep(data, use_fwhm=True, verbose=False)
        idx = obj['flags'] == 0

        ax = fig.add_subplot(111)
        plots.binned_map(obj['x'][idx], obj['y'][idx], obj['fwhm'][idx], bins=16, statistic='median', ax=ax)
        ax.set_title('%s - %s %s %s %s - half flux diameter mean %.2f median %.2f pix' % (posixpath.split(filename)[-1], image.site, image.ccd, image.filter, str(image.exposure), np.nanmean(obj['fwhm']), np.nanmedian(obj['fwhm'])))

    elif mode == 'wcs':
        wcs = WCS(header)

        if wcs is not None and wcs.is_celestial:
            # Detect objects
            obj = photometry.get_objects_sep(data, use_fwhm=True, wcs=wcs, verbose=False)

            pixscale = astrometry.get_pixscale(wcs=wcs)

            # Get stars from catalogue
            fram = Fram()
            ra0, dec0, sr0 = astrometry.get_frame_center(wcs=wcs, shape=data.shape)
            if ra0 is not None and sr0 is not None:
                if sr0 < 3.0:
                    cat = fram.get_stars(ra0, dec0, sr0, limit=100000, catalog='atlas', extra=['r > 8 and r < 15'])
                else:
                    cat = fram.get_stars(ra0, dec0, sr0, limit=100000, extra=['vt > 5 and vt < 11'])

                sr = 5.0 * pixscale * np.nanmedian(obj['fwhm'])

                # Match stars
                oidx, cidx, dist = astrometry.spherical_match(obj['ra'], obj['dec'], cat['ra'], cat['dec'], sr=sr)
                if len(dist):
                    order = np.argsort(dist)
                    oidx, cidx, dist = oidx[order], cidx[order], dist[order]
                    _, uniq_idx = np.unique(oidx, return_index=True)
                    oidx, cidx, dist = oidx[uniq_idx], cidx[uniq_idx], dist[uniq_idx]

                dist = dist * 3600

                idx = obj['flags'][oidx] == 0

                ax = fig.add_subplot(111)
                plots.binned_map(obj['x'][oidx][idx], obj['y'][oidx][idx], dist[idx], show_dots=True, bins=16, statistic='median', ax=ax)

                ax.set_title('%s - %s %s %s - displacement mean %.1f median %.1f arcsec pixel %.1f arcsec' % (posixpath.split(filename)[-1], image.site, image.ccd, image.filter, np.nanmean(dist[idx]), np.nanmedian(dist[idx]), pixscale*3600))

    elif mode == 'filters':
        mask = data > 30000
        if dark is not None:
            mask |= dark > np.median(dark) + 3.0*np.std(dark)

        wcs = WCS(header)

        if wcs is not None and wcs.is_celestial:
            pixscale = astrometry.get_pixscale(wcs=wcs)

            if request.GET.get('aper'):
                aper = float(request.GET.get('aper'))
                obj = photometry.get_objects_sep(data, wcs=wcs, aper=aper, use_fwhm=False, verbose=False, mask=mask)
            else:
                obj = photometry.get_objects_sep(data, wcs=wcs, use_fwhm=True, verbose=False, mask=mask)

            # Get stars from catalogue
            fram = Fram()
            ra0, dec0, sr0 = astrometry.get_frame_center(wcs=wcs, shape=data.shape)
            if ra0 is not None and sr0 is not None:
                if 'WF' not in header.get('CCD_NAME', ''):
                    cat = fram.get_stars(ra0, dec0, sr0, limit=100000, catalog='atlas', extra=['r < 17'])
                else:
                    cat = fram.get_stars(ra0, dec0, sr0, limit=100000, extra=['vt > 5 and vt < 11'])

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
                        verbose=False,
                    )
                    if match:
                        plots.plot_photometric_match(match, ax=ax, mode='color')
                        title = ax.get_title()
                        ax.set_title(f"{fname} {title}".strip())

    elif mode == 'zero':
        mask = data > 30000
        if dark is not None:
            mask |= dark > np.median(dark) + 3.0*np.std(dark)

        wcs = WCS(header)

        if wcs is not None and wcs.is_celestial:
            pixscale = astrometry.get_pixscale(wcs=wcs)

            if request.GET.get('aper'):
                aper = float(request.GET.get('aper'))
                obj = photometry.get_objects_sep(data, wcs=wcs, aper=aper, use_fwhm=False, verbose=False, mask=mask)
            else:
                obj = photometry.get_objects_sep(data, wcs=wcs, use_fwhm=True, verbose=False, mask=mask)

            aper = obj.meta.get('aper')

            # Get stars from catalogue
            fram = Fram()
            ra0, dec0, sr0 = astrometry.get_frame_center(wcs=wcs, shape=data.shape)
            if ra0 is not None and sr0 is not None:
                if 'WF' not in header.get('CCD_NAME', ''):
                    cat = fram.get_stars(ra0, dec0, sr0, limit=100000, catalog='atlas', extra=['r < 17'])
                else:
                    cat = fram.get_stars(ra0, dec0, sr0, limit=100000, extra=['vt > 5 and vt < 11'])

                sr = pixscale * np.nanmedian(obj['fwhm'])

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
                        verbose=False,
                    )

                    if match:
                        ax = fig.add_subplot(321)
                        plots.plot_photometric_match(match, ax=ax, mode='mag')

                        ax = fig.add_subplot(323)
                        plots.plot_photometric_match(match, ax=ax, mode='color')

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


from stdpipe import cutouts


@cache_page(3600)
@permission_required('auth.can_view_images', raise_exception=True)
def image_cutout(request, id=0, size=0, mode='view'):
    image = Images.objects.get(id=id)
    filename = image.filename
    filename = posixpath.join(settings.BASE_DIR, filename)

    data = fits.getdata(filename, -1)
    header = fits.getheader(filename, -1)

    # Clean up the header from COMMENT and HISTORY keywords that may break things
    header.remove('COMMENT', remove_all=True, ignore_missing=True)
    header.remove('HISTORY', remove_all=True, ignore_missing=True)

    cdark = find_calibration_image(image, 'masterdark')
    if cdark is not None:
        dark = fits.getdata(cdark.filename, -1)
        if cdark is not None:
            dark = fits.getdata(cdark.filename, -1)
        else:
            cbias,cdc = find_calibration_image(image, 'bias'), find_calibration_image(image, 'dcurrent')
            if cbias is not None and cdc is not None:
                bias = fits.getdata(cbias.filename, -1)
                dc = fits.getdata(cdc.filename, -1)

                dark = bias + image.exposure*dc
            else:
                dark = None

        if dark is not None:
            data,header = calibrate.calibrate(data, header, dark=dark) # Subtract dark and linearize

            cflat = find_calibration_image(image, 'masterflat')
            if cflat is not None:
                flat = fits.getdata(cflat.filename, -1)
                data *= np.median(flat)/flat

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
