from django.http import HttpResponse, FileResponse
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_protect
from django.db.models import Q

from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np
import json

from astropy.time import Time
from astropy.stats import mad_std

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


def get_lc(request):
    lc = Photometry.objects.order_by('time')

    night = request.GET.get('night')
    if night and night != 'all':
        lc = lc.filter(image__night=night)

    night1 = request.GET.get('night1')
    if night1:
        lc = lc.filter(image__night__gte=night1)

    night2 = request.GET.get('night2')
    if night2:
        lc = lc.filter(image__night__lte=night2)

    # Filter out bad data
    lc = lc.filter(Q(image__night__lt='20190216') | Q(image__night__gt='20190222'))

    site = request.GET.get('site')
    if site and site != 'all':
        lc = lc.filter(image__site=site)

    fname = request.GET.get('filter')
    if fname and fname != 'all':
        lc = lc.filter(filter=fname)

    ccd = request.GET.get('ccd')
    if ccd and ccd != 'all':
        lc = lc.filter(image__ccd=ccd)

    magerr = request.GET.get('magerr')
    if magerr:
        magerr = float(magerr)
        lc = lc.filter(magerr__lt=magerr)

    nstars = request.GET.get('nstars')
    if nstars:
        nstars = int(nstars)
        lc = lc.filter(nstars__gte=nstars)

    ra = float(request.GET.get('ra'))
    dec = float(request.GET.get('dec'))
    sr = float(request.GET.get('sr', 0.01))

    # Lc with centers within given search radius
    lc = lc.extra(
        where=['q3c_radial_query("photometry_all"."ra", "photometry_all"."dec", %s, %s, %s)'],
        params=(ra, dec, sr),
    )

    return lc


def lc(request, mode="jpg", size=800):
    lc = get_lc(request)

    # Fetch all data in a single query instead of iterating 10+ times
    data = list(
        lc.values_list(
            'time', 'image__site', 'image__ccd', 'filter', 'ra', 'dec',
            'mag', 'magerr', 'flags', 'fwhm', 'std', 'nstars',
            'color_term', 'zp_std', 'final_frac',
        )
    )

    if data:
        times, sites, ccds, filters, ras, decs, mags, magerrs, flags, fwhms, stds, nstars, color_term, zp_std, final_frac = zip(*data)
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
    else:
        times = sites = ccds = filters = ras = decs = mags = magerrs = flags = fwhms = stds = nstars = color_term = zp_std = final_frac = np.array([])

    mjds = Time(times).mjd if len(times) else []

    cols = np.array([{'B':'blue', 'V':'green', 'R':'red', 'I':'orange', 'z':'magenta'}.get(_, 'black') for _ in filters])

    ra = float(request.GET.get('ra'))
    dec = float(request.GET.get('dec'))
    sr = float(request.GET.get('sr', 0.01))
    name = request.GET.get('name')

    if name in ['sexadecimal', 'degrees']:
        name = None

    if request.GET.get('nofiltering'):
        filtering = False
    else:
        filtering = True

    # Quality cuts
    idx0 = np.ones_like(mags, dtype=bool)
    if filtering:
        mask = np.zeros_like(mags, dtype=bool)

        idx0 &= flags < 2

        for fn in np.unique(filters):
            idx = idx0 & (filters == fn)

            for _ in range(3):
                idx &= stds < np.median(stds[idx]) + 3.0*mad_std(stds[idx])

            for _ in range(3):
                idx &= fwhms < np.median(fwhms[idx]) + 3.0*mad_std(fwhms[idx])

            for _ in range(3):
                idx &= np.abs(color_term - np.median(color_term[idx])) < 3.0*mad_std(color_term[idx])

            for _ in range(3):
                idx &= zp_std < np.median(zp_std[idx]) + 3.0*mad_std(zp_std[idx])

            for _ in range(3):
                idx &= final_frac > np.median(final_frac[idx]) - 3.0*mad_std(final_frac[idx])

            mask |= idx

        idx0 = mask

    context = {}

    context['ra'] = ra
    context['dec'] = dec
    context['sr'] = sr
    context['filtering'] = filtering

    if name:
        title = '%s - ' % name
    else:
        title = ''

    title += '%.4f %.3f %.3f - %d pts' % (ra, dec, sr, len(mags))

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

            if len(mags[idx]) < 2:
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

            if len(mags[idx]) < 2:
                continue

            times_idx = [_.isoformat() for _ in times[idx]]

            lcs.append({'filter': fn, 'color': cols[idx][0],
                        'times': times_idx, 'mjds': list(mjds[idx]), 'xi': list(xi[idx]), 'eta': list(eta[idx]),
                        'mags': list(mags[idx]), 'magerrs': list(magerrs[idx]), 'flags': list(flags[idx]),
                        'fwhms': list(fwhms[idx]), 'stds': list(stds[idx]), 'nstars': list(nstars[idx])})

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
