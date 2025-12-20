from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import cache_page
# from django.views.decorators.csrf import csrf_protect

# import datetime, re, urllib
from urllib.parse import urlencode

from django.contrib import messages

from .models import Images
from .utils import redirect_get, db_query

# FRAM modules
from fram.resolve import resolve

from . import forms


# @cache_page(3600)
def index(request):
    context = {}

    sites = db_query('select site,count(*),(select night from images where site=i.site order by time desc limit 1) as last, (select night from images where site=i.site order by time asc limit 1) as first from images i group by i.site order by i.site;', (), simplify=False)

    context['sites'] = sites

    return TemplateResponse(request, 'index.html', context=context)


#@cache_page(3600)
def search(request, mode='images'):
    context = {}

    # Possible values for fields
    # TODO: properly cache these values

    # types = Images.objects.distinct('type').values('type')
    types = db_query("select fast_distinct(%s, %s) as type", ('images', 'type'))

    # sites = Images.objects.distinct('site').values('site')
    sites = db_query("select fast_distinct(%s, %s) as site", ('images', 'site'))

    # ccds = Images.objects.distinct('ccd').values('ccd')
    ccds = db_query("select fast_distinct(%s, %s) as ccd", ('images', 'ccd'))

    # serials = Images.objects.distinct('serial').values('serial')
    serials = db_query("select fast_distinct(%s, %s, 0) as serial", ('images', 'serial'))

    # filters = Images.objects.distinct('filter').values('filter')
    filters = db_query("select fast_distinct(%s, %s) as filter", ('images', 'filter'))

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
