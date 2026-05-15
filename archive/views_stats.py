from django.contrib.auth.decorators import permission_required
from django.http import JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

from .utils import db_query


STATS_CACHE_SECONDS = 3600


def _distribution(field):
    if field not in {"site", "ccd", "filter", "type"}:
        raise ValueError(f"Unsupported stats distribution field: {field}")

    return db_query(
        f"""
        select coalesce(nullif(label::text, ''), 'Unknown') as label,
               count
        from (
            select "{field}" as label,
                   count(*)::bigint as count
            from images
            group by "{field}"
        ) grouped
        order by count desc, label asc
        """,
        (),
        simplify=False,
    ) or []


def _archive_stats():
    summary = db_query(
        """
        select (select count(*)::bigint from images) as total_images,
               (
                   select count(*)::bigint
                   from (
                       select night
                       from images
                       where night is not null
                       group by night
                   ) nights
               ) as total_nights,
               (
                   select time
                   from images
                   where time is not null
                   order by time asc
                   limit 1
               ) as first_time,
               (
                   select time
                   from images
                   where time is not null
                   order by time desc
                   limit 1
               ) as last_time,
               (
                   select night
                   from images
                   where night is not null
                   order by night asc
                   limit 1
               ) as first_night,
               (
                   select night
                   from images
                   where night is not null
                   order by night desc
                   limit 1
               ) as last_night
        """,
        (),
    ) or {}

    timeline = db_query(
        """
        select substr(night, 1, 4) || '-' || substr(night, 5, 2) || '-01' as period,
               coalesce(nullif(site::text, ''), 'Unknown') as site,
               count(*)::bigint as count
        from images
        where night is not null
        group by substr(night, 1, 6), 1, 2
        order by 1, 2
        """,
        (),
        simplify=False,
    ) or []

    return {
        "summary": summary,
        "timeline": timeline,
        "distributions": {
            "sites": _distribution("site"),
            "ccds": _distribution("ccd"),
            "filters": _distribution("filter"),
            "types": _distribution("type"),
        },
        "generated_at": timezone.now(),
        "cache_seconds": STATS_CACHE_SECONDS,
    }


@require_GET
@permission_required("auth.can_view_images", raise_exception=True)
def stats(request):
    return TemplateResponse(
        request,
        "stats.html",
        context={"stats_json_url": reverse("stats_json")},
    )


@require_GET
def stats_redirect(request):
    return redirect("stats")


@require_GET
@permission_required("auth.can_view_images", raise_exception=True)
@cache_page(STATS_CACHE_SECONDS)
def stats_json(request):
    return JsonResponse(_archive_stats())
