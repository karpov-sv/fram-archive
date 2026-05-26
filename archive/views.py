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


@permission_required('auth.can_view_images', raise_exception=True)
def sky_view(request):
    hips_base_url = 'http://fram.fzu.cz/archive/hips/saturated/'
    hips_surveys = [
        {
            'id': 'FRAM/P/color',
            'name': 'FRAM color',
            'url': hips_base_url + 'color/',
        },
        {
            'id': 'FRAM/P/B',
            'name': 'FRAM B',
            'url': hips_base_url + 'B/',
        },
        {
            'id': 'FRAM/P/V',
            'name': 'FRAM V',
            'url': hips_base_url + 'V/',
        },
        {
            'id': 'FRAM/P/R',
            'name': 'FRAM R',
            'url': hips_base_url + 'R/',
        },
    ]

    context = {
        'hips_surveys': hips_surveys,
        'default_survey': hips_surveys[0],
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
        if form.is_valid():
            is_correct = True

            params = {}

            for _ in ['site', 'type', 'ccd', 'filter', 'night1', 'night2', 'serial', 'target', 'maxdist', 'filename', 'coords', 'magerr', 'nstars', 'nofiltering']:
                if form.cleaned_data.get(_) and form.cleaned_data[_] != 'all':
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
                    if sr > 1:
                        params['sr'] = 1

                    return redirect_get('images_cutouts',  get=params)

                elif mode == 'photometry':
                    # Restrict the radius
                    if sr > 5/60:
                        params['sr'] = 5/60

                    context['lc'] = reverse('photometry_lc') + '?' + urlencode(params)
                    context['lc_json'] = reverse('photometry_json') + '?' + urlencode(params)
                    context['lc_text'] = reverse('photometry_text') + '?' + urlencode(params)
                    context['lc_mjd'] = reverse('photometry_mjd') + '?' + urlencode(params)

        context.update(params)

    if mode == 'cutouts':
        return TemplateResponse(request, 'cutouts.html', context=context)
    elif mode == 'photometry':
        return TemplateResponse(request, 'photometry.html', context=context)
    else:
        return TemplateResponse(request, 'search.html', context=context)
