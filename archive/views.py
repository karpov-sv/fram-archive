from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_protect

import datetime, re, urllib
from urllib.parse import urlencode

from .models import Images
from .utils import permission_required_or_403, redirect_get, db_query

# FRAM modules
from fram.resolve import resolve


# @cache_page(3600)
def index(request):
    context = {}

    sites = db_query('select site,count(*),(select night from images where site=i.site order by time desc limit 1) as last, (select night from images where site=i.site order by time asc limit 1) as first from images i group by i.site order by i.site;', (), simplify=False)

    context['sites'] = sites

    return TemplateResponse(request, 'index.html', context=context)


#@cache_page(3600)
@csrf_protect
def search(request, mode='images'):
    context = {}

    message,message_cutout = None,None

    if request.method == 'POST':
        # Form submission handling

        params = {}

        for _ in ['site', 'type', 'ccd', 'filter', 'night1', 'night2', 'serial', 'target', 'maxdist', 'filename', 'coords', 'magerr', 'nstars', 'nofiltering']:
            if request.POST.get(_) and request.POST.get(_) != 'all':
                params[_] = request.POST.get(_)

        coords = request.POST.get('coords')
        if request.POST.get('sr_value'):
            sr = float(request.POST.get('sr_value', 0.1))*{'arcsec':1/3600, 'arcmin':1/60, 'deg':1}.get(request.POST.get('sr_units', 'deg'), 1)
            params['sr'] = sr
            params['sr_value'] = request.POST.get('sr_value')
            params['sr_units'] = request.POST.get('sr_units')
        else:
            sr = 0
        name,ra,dec = resolve(coords)

        if name:
            params['name'] = name
            params['ra'] = ra
            params['dec'] = dec

        if name or mode == 'images':
            if mode == 'cutouts':
                # Search cutouts only
                if sr > 1:
                    params['sr'] = 1

                return redirect_get('images_cutouts',  get=params)

            elif mode == 'photometry':
                # Search photometry database
                if sr > 5/60:
                    params['sr'] = 5/60
                    params['sr_value'] = 1
                    params['sr_units'] = 'arcmin'

                context['lc'] = reverse('photometry_lc') + '?' + urlencode(params)
                context['lc_json'] = reverse('photometry_json') + '?' + urlencode(params)
                context['lc_text'] = reverse('photometry_text') + '?' + urlencode(params)
                context['lc_mjd'] = reverse('photometry_mjd') + '?' + urlencode(params)

            elif mode == 'images':
                # Search full images
                if name and not sr:
                    context['message'] = "Search radius not set"
                else:
                    return redirect_get('images',  get=params)

        else:
            context['message'] = "Can't resolve query position: " + coords

        context.update(params)

    # Possible values for fields
    # types = Images.objects.distinct('type').values('type')
    types = db_query("select fast_distinct(%s, %s) as type", ('images', 'type'))
    context['types'] = types

    # sites = Images.objects.distinct('site').values('site')
    sites = db_query("select fast_distinct(%s, %s) as site", ('images', 'site'))
    context['sites'] = sites

    # ccds = Images.objects.distinct('ccd').values('ccd')
    ccds = db_query("select fast_distinct(%s, %s) as ccd", ('images', 'ccd'))
    context['ccds'] = ccds

    # serials = Images.objects.distinct('serial').values('serial')
    serials = db_query("select fast_distinct(%s, %s, 0) as serial", ('images', 'serial'))
    context['serials'] = serials

    # filters = Images.objects.distinct('filter').values('filter')
    filters = db_query("select fast_distinct(%s, %s) as filter", ('images', 'filter'))
    context['filters'] = filters

    if mode == 'cutouts':
        return TemplateResponse(request, 'cutouts.html', context=context)
    elif mode == 'photometry':
        return TemplateResponse(request, 'photometry.html', context=context)
    else:
        return TemplateResponse(request, 'search.html', context=context)
