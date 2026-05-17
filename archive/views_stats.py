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


def _timeline(granularity="month"):
    if granularity == "day":
        period_sql = "substr(night, 1, 4) || '-' || substr(night, 5, 2) || '-' || substr(night, 7, 2)"
    else:
        period_sql = "substr(month, 1, 4) || '-' || substr(month, 5, 2) || '-01'"

    return db_query(
        f"""
        select {period_sql} as period,
               coalesce(nullif(site::text, ''), 'Unknown') as site,
               sum(nimages)::bigint as count
        from image_stats_daily_site
        group by 1, 2
        order by 1, 2
        """,
        (),
        simplify=False,
    ) or []


def _distribution(field):
    if field not in {"site", "ccd", "filter", "type"}:
        raise ValueError(f"Unsupported stats distribution field: {field}")

    return db_query(
        f"""
        select coalesce(nullif("{field}"::text, ''), 'Unknown') as label,
               sum(nimages)::bigint as count
        from image_stats_type
        group by 1
        order by count desc, label asc
        """,
        (),
        simplify=False,
    ) or []


def _configuration_summary():
    return db_query(
        """
        select coalesce(nullif(site::text, ''), 'Unknown') as site,
               coalesce(nullif(ccd::text, ''), 'Unknown') as ccd,
               coalesce(serial::text, 'Unknown') as serial,
               min(night) as first_night,
               max(night) as last_night,
               count(*)::bigint as nimages
        from images
        group by 1, 2, 3
        order by site,
                 ccd,
                 min(night),
                 serial
        """,
        (),
        simplify=False,
    ) or []


def _archive_stats():
    summary = db_query(
        """
        select (select sum(nimages)::bigint from image_stats_site) as total_images,
               (select count(distinct night)::bigint from image_stats_daily_site) as total_nights,
               (select min(first_time) from image_stats_site) as first_time,
               (select max(last_time) from image_stats_site) as last_time,
               (select min(first_night) from image_stats_site) as first_night,
               (select max(last_night) from image_stats_site) as last_night
        """,
        (),
    ) or {}

    return {
        "summary": summary,
        "timeline": _timeline("month"),
        "timeline_granularity": "month",
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
        context={
            "stats_json_url": reverse("stats_json"),
            "timeline_json_url": reverse("stats_timeline_json"),
            "configuration_json_url": reverse("stats_configuration_json"),
        },
    )


@require_GET
def stats_redirect(request):
    return redirect("stats")


@require_GET
@permission_required("auth.can_view_images", raise_exception=True)
@cache_page(STATS_CACHE_SECONDS)
def stats_json(request):
    return JsonResponse(_archive_stats())


@require_GET
@permission_required("auth.can_view_images", raise_exception=True)
@cache_page(STATS_CACHE_SECONDS)
def stats_timeline_json(request):
    granularity = request.GET.get("granularity", "month")
    if granularity not in {"month", "day"}:
        granularity = "month"

    return JsonResponse({
        "timeline": _timeline(granularity),
        "timeline_granularity": granularity,
        "generated_at": timezone.now(),
        "cache_seconds": STATS_CACHE_SECONDS,
    })


@require_GET
@permission_required("auth.can_view_images", raise_exception=True)
@cache_page(STATS_CACHE_SECONDS)
def stats_configuration_json(request):
    return JsonResponse({
        "configuration": _configuration_summary(),
        "generated_at": timezone.now(),
        "cache_seconds": STATS_CACHE_SECONDS,
    })
