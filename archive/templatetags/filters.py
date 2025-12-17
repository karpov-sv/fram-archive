from django import template
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe

import datetime, re
import numpy as np
import markdown
import uuid

register = template.Library()


@register.filter
def qs_length(value):
    if type(value) == list:
        return len(value)
    else:
        return value.count()


@register.filter
def addstr(value, arg):
    return str(value) + str(arg)


@register.filter
def subtract(value, arg):
    return value - arg


@register.filter
def multiply(value, arg):
    return value*arg


@register.filter
def GET_remove(value, key):
    value = value.copy()

    if key in value:
        value.pop(key)

    return value


@register.filter
def GET_append(value, key, new=1):
    value = value.copy()

    if key in value:
        value.pop(key)

    if '=' in key:
        s = key.split('=')
        value.appendlist(s[0], s[1])
    else:
        value.appendlist(key, new)

    return value


@register.filter
def GET_urlencode(value):
    return value.urlencode()


@register.filter
def fromtimestamp(value):
    return datetime.datetime.fromtimestamp(float(value))


@register.filter
def make_label(text, type="primary"):
    return mark_safe("<span class='label label-" + type + "'>" + text + "</span>");


@register.filter
def urlify_news(string):
    string = re.sub(r'\b(\d\d\d\d_\d\d_\d\d)\b', night_url, string)

    return mark_safe(string)


@register.filter
def night_date(night):
    return datetime.datetime.strptime(night.night, '%Y_%m_%d')


@register.filter
def linecount(text):
    return 0


@register.filter
def make_uuid(x):
    return str(uuid.uuid1())


@register.filter
def to_sexadecimal(value, plus=False):
    avalue = np.abs(value)
    deg = int(np.floor(avalue))
    min = int(np.floor(60.0*(avalue - deg)))
    sec = 3600.0*(avalue - deg - 1.0*min/60)

    string = '%02d %02d %04.1f' % (deg, min, sec)

    if value < 0:
        string = '-' + string
    elif plus:
        string = '+' + string

    return string


@register.filter
def to_sexadecimal_plus(value):
    return to_sexadecimal(value, plus=True)


@register.filter
def to_sexadecimal_hours(value):
    return to_sexadecimal(value*1.0/15)


@register.filter
def split(value, arg):
    return value.split(arg)


@register.filter
def markdownify(text):
    # safe_mode governs how the function handles raw HTML
    return markdown.markdown(text, safe_mode='escape')


@register.filter
def get(d, key):
    return d.get(key, '')


@register.filter
def seconds_since(t, t0):
    return (t - t0).total_seconds()


@register.filter
def header_to_string(header):
    try:
        contents = []

        for card in header.cards:
            cstr = str(card)

            if m := re.match(r'^((HISTORY)|(COMMENT|END))\b(.*)$', cstr):
                contents.append(
                    f"<span class='text-secondary'>{m[1]}</span>"
                    f"<span class='text-info'>{m[4]}</span>"
                )
            elif m := re.match(r'^([^=]+)=(\s*(\'.*?\'|\S+)\s*)(/.*)?$', cstr):
                contents.append(
                    f"<span class='text-primary'>{m[1]}</span>"
                    f"<span class='text-secondary'>=</span>"
                    f"<span class='text-body-emphasis'>{m[2]}</span>"
                    f"<span class='text-info'>{m[4] or ''}</span>"
                )
            elif cstr:
                contents.append(cstr)

        contents = "\n".join(contents)

    except KeyboardInterrupt:
        contents = "Cannot display FITS header"

    return mark_safe(contents)


@register.filter
def user(user):
    """
    Format User object in a readable way
    """
    result = ""

    if user.first_name or user.last_name:
        result = user.first_name + " " + user.last_name
    else:
        result = user.username

    return result
