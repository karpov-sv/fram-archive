from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import cache_page
# from django.views.decorators.csrf import csrf_protect

# import datetime, re, urllib
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import permission_required

from .utils import redirect_get, db_query, image_stats_distinct

# FRAM modules
from fram.resolve import resolve

from . import forms


# All-sky mosaic co-added from the survey frames, in HiPS format. Served
# publicly, which is what lets CDS render cutouts of it below.
HIPS_BASE_URL = 'http://fram.fzu.cz/archive/hips/saturated/'

# CDS service rendering a cutout of any HiPS into a plain image
HIPS2FITS_URL = 'https://alasky.cds.unistra.fr/hips-image-services/hips2fits'

# Deeper color imaging to compare the survey field with. Pan-STARRS covers the
# sky north of dec -30 only, and renders a blank white image below it, so the
# southern fields - which is most of what CTA-S observes - fall back to DSS2.
PANSTARRS_HIPS = 'CDS/P/PanSTARRS/DR1/color-z-zg-g'
PANSTARRS_MIN_DEC = -30.0
DSS_HIPS = 'CDS/P/DSS2/color'

# Field of view of the position previews, in degrees. A wide-field pixel is
# about 6 arcsec, so this is roughly a hundred of them across.
PREVIEW_FOV = 10.0/60
PREVIEW_SIZE = 200  # Requested size of the previews, in pixels


def hips2fits_url(hips, ra, dec, fov=PREVIEW_FOV, size=PREVIEW_SIZE):
    """URL of a rendered cutout of a HiPS around the given position.

    The color surveys used here carry their own colors, so no stretch or
    colormap is asked for - hips2fits ignores those for a color HiPS anyway.
    """
    return HIPS2FITS_URL + '?' + urlencode({
        'hips': hips,
        'ra': ra, 'dec': dec, 'fov': fov,
        'width': size, 'height': size,
        'projection': 'TAN', 'coordsys': 'icrs', 'format': 'jpg',
    })


# Field of view the sky view opens at when followed from a preview, in degrees.
# Wider than the preview itself, so that the position arrives with some context
# around it rather than filling the screen.
PREVIEW_LINK_FOV = 0.25


def position_previews(ra, dec):
    """Small images of the sky around the position, to judge its crowding.

    The FRAM mosaic shows what the survey itself sees, at the resolution the
    photometry is measured at, while the deeper and sharper atlas image next to
    it reveals the neighbours actually blended into a measurement. Only the FRAM
    one carries a link, as the sky view shows that very mosaic.
    """
    if dec > PANSTARRS_MIN_DEC:
        atlas = {'name': 'Pan-STARRS', 'hips': PANSTARRS_HIPS}
    else:
        atlas = {'name': 'DSS2', 'hips': DSS_HIPS}

    return [
        {
            'name': 'FRAM-CTA',
            'url': hips2fits_url(HIPS_BASE_URL + 'color/', ra, dec),
            'link': reverse('sky_view') + '?' + urlencode({
                'ra': ra, 'dec': dec, 'fov': PREVIEW_LINK_FOV,
            }),
            'title': 'Open this position in the sky view',
        },
        {'name': atlas['name'], 'url': hips2fits_url(atlas['hips'], ra, dec)},
    ]


# @cache_page(3600)
def index(request):
    context = {}

    sites = db_query(
        '''
        select site,
               nimages as count,
               first_night as first,
               last_night as last
        from image_stats_site
        order by site
        ''',
        (),
        simplify=False,
    )

    context['sites'] = sites

    return TemplateResponse(request, 'index.html', context=context)


def links(request):
    return TemplateResponse(request, 'links.html')


# Where the sky view opens when no position is asked for
SKY_DEFAULT_TARGET = 'M45'
SKY_DEFAULT_FOV = 5.0


@permission_required('auth.can_view_images', raise_exception=True)
def sky_view(request):
    hips_surveys = [
        {
            'id': 'FRAM/P/color',
            'name': 'FRAM color',
            'url': HIPS_BASE_URL + 'color/',
        },
        {
            'id': 'FRAM/P/B',
            'name': 'FRAM B',
            'url': HIPS_BASE_URL + 'B/',
        },
        {
            'id': 'FRAM/P/V',
            'name': 'FRAM V',
            'url': HIPS_BASE_URL + 'V/',
        },
        {
            'id': 'FRAM/P/R',
            'name': 'FRAM R',
            'url': HIPS_BASE_URL + 'R/',
        },
    ]

    # Optional position to open at, as followed from a photometry preview. The
    # target is formatted here rather than in the template, so that it reaches
    # Aladin as the plain 'ra dec' string it expects whatever the locale.
    try:
        target = '%.6f %.6f' % (float(request.GET['ra']), float(request.GET['dec']))
    except (KeyError, TypeError, ValueError):
        target = SKY_DEFAULT_TARGET

    try:
        fov = float(request.GET['fov'])
    except (KeyError, TypeError, ValueError):
        fov = SKY_DEFAULT_FOV

    # Degrees, and neither a point nor more than the whole sky
    fov = min(max(fov, 1.0/3600), 180.0)

    context = {
        'hips_surveys': hips_surveys,
        'default_survey': hips_surveys[0],
        'initial_target': target,
        'initial_fov': fov,
    }

    return TemplateResponse(request, 'sky.html', context=context)


#@cache_page(3600)
def search(request, mode='images'):
    context = {}

    # Possible values for fields
    # TODO: properly cache these values

    types = image_stats_distinct('type')

    sites = image_stats_distinct('site')

    ccds = image_stats_distinct('ccd')

    serials = image_stats_distinct('serial')

    filters = image_stats_distinct('filter')

    form = forms.ImagesSearchForm(
        request.POST or None,
        mode=mode,
        types=types, sites=sites, ccds=ccds, serials=serials, filters=filters,
    )
    context['form'] = form

    if request.method == "POST":
        params = {}

        if form.is_valid():
            is_correct = True

            for _ in ['site', 'type', 'ccd', 'filter', 'night1', 'night2', 'serial', 'target', 'maxdist', 'filename', 'coords', 'magerr', 'nstars', 'nofiltering', 'sigma',
                      'average', 'average_window', 'average_mode', 'colors',
                      'color_aware', 'bv']:
                value = form.cleaned_data.get(_)

                # A color of exactly zero is a color like any other, unlike every
                # other numeric field here, where the empty value and the zero
                # both mean the option is off
                if _ == 'bv':
                    keep = value is not None
                else:
                    keep = bool(value) and value != 'all'

                if keep:
                    params[_] = request.POST.get(_)

            if form.cleaned_data.get('coords'):
                coords = form.cleaned_data['coords']
                name,ra,dec = resolve(coords)

                if name:
                    params['name'] = name
                    params['ra'] = ra
                    params['dec'] = dec
                else:
                    messages.error(request, "Cannot resolve query position: " + coords)
                    is_correct = False

            if form.cleaned_data.get('sr_value'):
                sr = float(form.cleaned_data.get('sr_value', 0.1))
                sr *= {'arcsec':1/3600, 'arcmin':1/60, 'deg':1}.get(form.cleaned_data.get('sr_units', 'deg'), 1)

                params['sr'] = sr
            else:
                if mode == 'cutouts':
                    params['sr'] = 0.1

            if is_correct:
                if mode == 'images':
                    return redirect_get('images',  get=params)

                elif mode == 'cutouts':
                    # Restrict the radius
                    params['sr'] = min(params['sr'], 1)

                    return redirect_get('images_cutouts',  get=params)

                elif mode == 'photometry':
                    # Restrict the radius, if it is set at all
                    if 'sr' in params:
                        params['sr'] = min(params['sr'], 5/60)

                    context['lc'] = reverse('photometry_lc') + '?' + urlencode(params)
                    context['lc_json'] = reverse('photometry_json') + '?' + urlencode(params)
                    context['lc_text'] = reverse('photometry_text') + '?' + urlencode(params)
                    context['lc_mjd'] = reverse('photometry_mjd') + '?' + urlencode(params)
                    context['lc_period'] = reverse('photometry_period') + '?' + urlencode(params)

                    # Only the resolved queries have a position to preview
                    if 'ra' in params:
                        context['previews'] = position_previews(params['ra'], params['dec'])
                        context['preview_fov'] = PREVIEW_FOV*60  # arcmin, for the caption

        context.update(params)

    if mode == 'cutouts':
        return TemplateResponse(request, 'cutouts.html', context=context)
    elif mode == 'photometry':
        return TemplateResponse(request, 'photometry.html', context=context)
    else:
        return TemplateResponse(request, 'search.html', context=context)
