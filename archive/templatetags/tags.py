from django import template
from django.urls import get_script_prefix

register = template.Library()


@register.simple_tag(takes_context=True)
def get_root(context):
    #return context['request'].path
    return get_script_prefix()
