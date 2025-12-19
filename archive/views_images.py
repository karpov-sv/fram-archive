from django.http import HttpResponse, FileResponse
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.decorators import permission_required
from django.conf import settings

from django.db.models import Count

import os, sys, posixpath
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib import colormaps
import numpy as np

import cv2

import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

from skimage.transform import rescale
from io import BytesIO

from astropy.io import fits
from astropy.wcs import WCS

from esutil import htm

from .models import Images, Calibrations
from .utils import permission_required_or_403

# FRAM modules
from fram import calibrate
from fram import survey
from fram import utils
from fram.fram import Fram, parse_iso_time, get_night


# TODO: memoize the result
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
    types = images.distinct('type').values('type')
    context['types'] = types

    sites = images.distinct('site').values('site')
    context['sites'] = sites

    ccds = images.distinct('ccd').values('ccd')
    context['ccds'] = ccds

    filters = images.distinct('filter').values('filter')
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
    sites = images.distinct('site').values('site')
    context['sites'] = sites

    ccds = images.distinct('ccd').values('ccd')
    context['ccds'] = ccds

    filters = images.distinct('filter').values('filter')
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


@cache_page(3600)
@permission_required('auth.can_view_images', raise_exception=True)
def image_preview(request, id=0, size=0):
    image = Images.objects.get(id=id)
    filename = image.filename
    filename = posixpath.join(settings.BASE_DIR, filename)

    data = fits.getdata(filename, -1)
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

        ldata = data
    else:
        ldata,lheader = calibrate.crop_overscans(data, header, subtract=False)

    if size:
        data = rescale(data, size/data.shape[1], mode='reflect', anti_aliasing=True, preserve_range=True)

    limits = np.percentile(ldata[np.isfinite(ldata)], [2.5, float(request.GET.get('qq', 99.75))])

    # figsize = (data.shape[1], data.shape[0])

    # fig = Figure(facecolor='white', dpi=72, figsize=(figsize[0]/72, figsize[1]/72))

    # fig.figimage(data, vmin=limits[0], vmax=limits[1], origin='lower', cmap=request.GET.get('cmap', 'Blues_r'))

    # canvas = FigureCanvas(fig)

    # response = HttpResponse(content_type='image/jpeg')
    # canvas.print_jpg(response)

    data = (data - limits[0]) / (limits[1] - limits[0])
    data = np.clip(data, 0.0, 1.0)

    cmap = colormaps[request.GET.get('cmap', 'Blues_r')]
    data = cmap(data) # RGBA

    data = (255 * data).astype(np.uint8)

    # OpenCV expects BGRA
    data = cv2.cvtColor(data, cv2.COLOR_RGBA2BGRA)

    success, buf = cv2.imencode(
        ".jpg",
        data,
        [cv2.IMWRITE_JPEG_QUALITY, int(request.GET.get('quality', 75))]
    )
    if not success:
        return HttpResponse(status=500)

    return HttpResponse(
        buf.tobytes(),
        content_type="image/jpeg"
    )

    return response


@permission_required('auth.can_view_images', raise_exception=True)
def image_download(request, id, raw=True):
    image = Images.objects.get(id=id)

    filename = image.filename
    filename = posixpath.join(settings.BASE_DIR, filename)

    if raw or image.type in ['masterdark', 'masterflat', 'dcurrent', 'bias']:
        response = HttpResponse(FileResponse(file(filename)), content_type='application/octet-stream')
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
def images_nights(request):
    # nights = Images.objects.order_by('-night').values('night').annotate(count=Count('night'))
    nights = Images.objects.values('night','site').annotate(count=Count('id')).order_by('-night','site')

    site = request.GET.get('site')
    if site and site != 'all':
        nights = nights.filter(site=site)

    context = {'nights':nights}

    sites = Images.objects.distinct('site').values('site')
    context['sites'] = sites

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

    if mode == 'zero':
        fig = Figure(facecolor='white', dpi=72, figsize=(16,8), tight_layout=True)
    else:
        fig = Figure(facecolor='white', dpi=72, figsize=(14,12), tight_layout=True)

    if mode == 'bg':
        # Extract the background
        import sep
        bg = sep.Background(data.astype(np.double))

        ax = fig.add_subplot(111)
        utils.imshow(bg.back(), ax=ax, origin='lower')
        ax.set_title('%s - %s %s %s %s - bg mean %.2f median %.2f rms %.2f' % (posixpath.split(filename)[-1], image.site, image.ccd, image.filter, str(image.exposure), np.mean(bg.back()), np.median(bg.back()), np.std(bg.back())))

    elif mode == 'fwhm':
        # Detect objects and plot their FWHM
        obj = survey.get_objects_sep(data, use_fwhm=True)
        idx = obj['flags'] == 0

        ax = fig.add_subplot(111)
        utils.binned_map(obj['x'][idx], obj['y'][idx], obj['fwhm'][idx], bins=16, statistic='median', ax=ax)
        ax.set_title('%s - %s %s %s %s - half flux diameter mean %.2f median %.2f pix' % (posixpath.split(filename)[-1], image.site, image.ccd, image.filter, str(image.exposure), np.mean(obj['fwhm']), np.median(obj['fwhm'])))

    elif mode == 'wcs':
        # Detect objects
        obj = survey.get_objects_sep(data, use_fwhm=True, verbose=False)
        wcs = WCS(header)

        if wcs is not None:
            obj['ra'],obj['dec'] = wcs.all_pix2world(obj['x'], obj['y'], 0)

            pixscale = np.hypot(wcs.pixel_scale_matrix[0,0], wcs.pixel_scale_matrix[0,1])

            # Get stars from catalogue
            fram = Fram()
            ra0,dec0,sr0 = survey.get_frame_center(header=header)
            if sr0 < 3.0:
                cat = fram.get_stars(ra0, dec0, sr0, limit=100000, catalog='atlas', extra=['r > 8 and r < 15'])
            else:
                cat = fram.get_stars(ra0, dec0, sr0, limit=100000, extra=['vt > 5 and vt < 11'])
            x,y = wcs.all_world2pix(cat['ra'], cat['dec'], 0)

            sr = 5.0*pixscale*np.median(obj['fwhm'])

            # Match stars
            h = htm.HTM(10)
            m = h.match(obj['ra'],obj['dec'], cat['ra'],cat['dec'], sr, maxmatch=1)
            oidx = m[0]
            cidx = m[1]
            dist = m[2]*3600

            idx = obj['flags'][oidx] == 0

            ax = fig.add_subplot(111)
            utils.binned_map(obj['x'][oidx][idx], obj['y'][oidx][idx], dist[idx], show_dots=True, bins=16, statistic='median', ax=ax)

            ax.set_title('%s - %s %s %s - displacement mean %.1f median %.1f arcsec pixel %.1f arcsec' % (posixpath.split(filename)[-1], image.site, image.ccd, image.filter, np.mean(dist[idx]), np.median(dist[idx]), pixscale*3600))

    elif mode == 'filters':
        mask = data > 30000
        if dark is not None:
            mask |= dark > np.median(dark) + 3.0*np.std(dark)

        wcs = WCS(header)

        if wcs is not None:
            pixscale = np.hypot(wcs.pixel_scale_matrix[0,0], wcs.pixel_scale_matrix[0,1])

            if request.GET.get('aper'):
                obj = survey.get_objects_sep(data, wcs=wcs, aper=float(request.GET.get('aper')), use_fwhm=False, verbose=False)
            else:
                obj = survey.get_objects_sep(data, wcs=wcs, use_fwhm=True, verbose=False)

            # Get stars from catalogue
            fram = Fram()
            ra0,dec0,sr0 = survey.get_frame_center(header=header)
            if 'WF' not in header['CCD_NAME']:
                cat = fram.get_stars(ra0, dec0, sr0, limit=100000, catalog='atlas', extra=['r < 17'])
            else:
                cat = fram.get_stars(ra0, dec0, sr0, limit=100000, extra=['vt > 5 and vt < 11'])

            for i,fname in enumerate(['B', 'V', 'R', 'I']):
                ax = fig.add_subplot(2, 2, i+1)
                match = survey.match_objects(obj, cat, pixscale*np.median(obj['fwhm']), fname=fname)
                ax.errorbar(match['cB']-match['cV'], match['Y']-match['YY'], match['tmagerr'], fmt='.', capsize=0, alpha=0.2, color='gray')
                ax.plot((match['cB']-match['cV'])[match['idx']], (match['Y']-match['YY'])[match['idx']], '.', color='red', label=fname, alpha=1.0)
                ax.legend()
                ax.axhline(0, color='black', alpha=0.5)
                ax.set_xlabel('B-V')
                ax.set_ylabel('Instr - model')
                ax.set_xlim(-0.0, 2.0)
                ax.set_ylim(-1.5, 1.5)

    elif mode == 'zero':
        mask = data > 30000
        if dark is not None:
            mask |= dark > np.median(dark) + 3.0*np.std(dark)

        wcs = WCS(header)

        if wcs is not None:
            pixscale = np.hypot(wcs.pixel_scale_matrix[0,0], wcs.pixel_scale_matrix[0,1])

            if request.GET.get('aper'):
                obj = survey.get_objects_sep(data, wcs=wcs, aper=float(request.GET.get('aper')), use_fwhm=False, verbose=False)
            else:
                obj = survey.get_objects_sep(data, wcs=wcs, use_fwhm=True, verbose=False)

            # Get stars from catalogue
            fram = Fram()
            ra0,dec0,sr0 = survey.get_frame_center(header=header)
            if 'WF' not in header['CCD_NAME']:
                cat = fram.get_stars(ra0, dec0, sr0, limit=100000, catalog='atlas', extra=['r < 17'])
            else:
                cat = fram.get_stars(ra0, dec0, sr0, limit=100000, extra=['vt > 5 and vt < 11'])

            match = survey.match_objects(obj, cat, pixscale*np.median(obj['fwhm']), fname=header['FILTER'])

            ax = fig.add_subplot(321)
            ax.errorbar(match['cmag'], match['Y']-match['YY'], match['tmagerr'], fmt='.', capsize=0, color='blue', alpha=0.2)
            ax.plot(match['cmag'][match['idx']], (match['Y']-match['YY'])[match['idx']], '.', color='red', alpha=0.5)
            ax.axhline(0, ls=':', alpha=0.8, color='black')
            ax.set_xlabel('Catalogue mag')
            ax.set_ylabel('Instrumental - Model')
            ax.set_ylim(-1.5,1.5)

            ax = fig.add_subplot(323)
            ax.errorbar(match['cB']-match['cV'], match['Y']-match['YY'], match['tmagerr'], fmt='.', capsize=0, alpha=0.3)
            ax.plot((match['cB']-match['cV'])[match['idx']], (match['Y']-match['YY'])[match['idx']], '.', color='red', alpha=0.3)
            ax.axhline(0, ls=':', alpha=0.8, color='black')
            ax.set_xlabel('B-V')
            ax.set_ylabel('Instrumental - Model')
            ax.set_ylim(-1.5,1.5)
            ax.set_xlim(-1.0,4)

            ax = fig.add_subplot(325)
            ax.hist(match['mag'], bins=100)
            ax.set_xlabel('Catalogue mag')

            ax = fig.add_subplot(122)
            utils.binned_map(obj['x'][match['oidx']][match['idx']], obj['y'][match['oidx']][match['idx']], match['Y'][match['idx']], bins=8, aspect='equal', ax=ax)
            ax.set_title('filter %s aper %.1f' % (header['FILTER'], obj['aper']))

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

    figsize = (crop.shape[1], crop.shape[0])

    fig = Figure(facecolor='white', dpi=72, figsize=(figsize[0]/72, figsize[1]/72))

    if np.any(np.isfinite(crop)):
        limits = np.percentile(crop[np.isfinite(crop)], [0.5, float(request.GET.get('qq', 99.75))])
        fig.figimage(crop, vmin=limits[0], vmax=limits[1], origin='lower', cmap=request.GET.get('cmap', 'Blues_r'))

    canvas = FigureCanvas(fig)

    response = HttpResponse(content_type='image/jpeg')
    canvas.print_jpg(response)

    return response
