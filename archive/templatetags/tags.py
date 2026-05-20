from django import template
from django.urls import get_script_prefix
from urllib.parse import urlencode

register = template.Library()


@register.simple_tag(takes_context=True)
def get_root(context):
    #return context['request'].path
    return get_script_prefix()


@register.simple_tag
def encode_params(**kwargs):
    params = {}

    for key, value in kwargs.items():
        if value is None or value == '' or value == 'all':
            continue

        params[key] = value

    return urlencode(params)
