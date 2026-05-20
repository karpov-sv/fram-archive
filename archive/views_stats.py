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

TARGET_CLASSES = [
    {
        "class": "GRBs",
        "target_min": 50000,
        "target_max": 90000,
    },
    {
        "class": "Survey",
        "targets": [
            60,
            3926, 3931, 3933, 3935, 3936, 3946,
            1045, 1047, 1055, 1058, 1059],
    },
    {
        "class": "Calibration Experiments",
        "target_min": 70,
        "target_max": 99,
    },
    {
        "class": "Auger Showers",
        "targets": [12],
    },
    {
        "class": "Fake Showers",
        "targets": [6001, 6009],
    },
    {
        "class": "VAOD Scans",
        "targets": [2000, 2001, 6002],
    },
]


def _timeline(granularity="month"):
    if granularity == "day":
        period_sql = "SUBSTR(night, 1, 4) || '-' || SUBSTR(night, 5, 2) || '-' || SUBSTR(night, 7, 2)"
    else:
        period_sql = "SUBSTR(month, 1, 4) || '-' || SUBSTR(month, 5, 2) || '-01'"

    return db_query(
        f"""
        SELECT {period_sql} AS period,
               COALESCE(NULLIF(site::TEXT, ''), 'Unknown') AS site,
               SUM(nimages)::BIGINT AS count
        FROM image_stats_daily_site
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        (),
        simplify=False,
    ) or []


def _distribution(field):
    if field not in {"site", "ccd", "filter", "type"}:
        raise ValueError(f"Unsupported stats distribution field: {field}")

    return db_query(
        f"""
        SELECT COALESCE(NULLIF("{field}"::TEXT, ''), 'Unknown') AS label,
               SUM(nimages)::BIGINT AS count
        FROM image_stats_type
        GROUP BY 1
        ORDER BY count DESC, label ASC
        """,
        (),
        simplify=False,
    ) or []


def _target_class_distribution():
    class_cases = []
    class_params = []

    for target_class in TARGET_CLASSES:
        criteria = []

        if target_class.get("targets"):
            placeholders = ", ".join(["%s"] * len(target_class["targets"]))
            criteria.append(f"target IN ({placeholders})")
            class_params.extend(target_class["targets"])

        range_criteria = []
        if target_class.get("target_min") is not None:
            range_criteria.append("target >= %s")
            class_params.append(target_class["target_min"])

        if target_class.get("target_max") is not None:
            range_criteria.append("target < %s")
            class_params.append(target_class["target_max"])

        if range_criteria:
            criteria.append("(" + " AND ".join(range_criteria) + ")")

        if criteria:
            class_cases.append(
                "WHEN "
                + " OR ".join(criteria)
                + " THEN %s"
            )
            class_params.append(target_class["class"])

    if class_cases:
        class_sql = " ".join(class_cases)
        params = tuple(class_params)
    else:
        class_sql = ""
        params = ()

    return db_query(
        f"""
        SELECT target_class AS label,
               COUNT(*)::BIGINT AS count
        FROM (
            SELECT CASE
                   {class_sql}
                   ELSE 'Other'
                   END AS target_class
            FROM images
            WHERE type = 'object'
        ) classified
        GROUP BY target_class
        ORDER BY count DESC, label ASC
        """,
        params,
        simplify=False,
    ) or []


def _configuration_summary():
    return db_query(
        """
        WITH nightly AS (
            SELECT COALESCE(NULLIF(site::TEXT, ''), 'Unknown') AS site,
                   COALESCE(NULLIF(ccd::TEXT, ''), 'Unknown') AS ccd,
                   COALESCE(serial::TEXT, 'Unknown') AS serial,
                   night,
                   MIN(time) AS first_time,
                   COUNT(*)::BIGINT AS nimages
            FROM images
            GROUP BY 1, 2, 3, 4
        ),
        ordered AS (
            SELECT *,
                   CASE
                       WHEN serial IS DISTINCT FROM LAG(serial) OVER (
                           PARTITION BY site, ccd
                           ORDER BY night NULLS LAST, first_time NULLS LAST, serial
                       )
                       THEN 1 ELSE 0
                   END AS starts_segment
            FROM nightly
        ),
        segmented AS (
            SELECT *,
                   SUM(starts_segment) OVER (
                       PARTITION BY site, ccd
                       ORDER BY night NULLS LAST, first_time NULLS LAST, serial
                       ROWS UNBOUNDED PRECEDING
                   ) AS segment_id
            FROM ordered
        )
        SELECT site,
               ccd,
               serial,
               MIN(night) AS first_night,
               MAX(night) AS last_night,
               SUM(nimages)::BIGINT AS nimages
        FROM segmented
        GROUP BY site, ccd, segment_id, serial
        ORDER BY site,
                 ccd,
                 MIN(night) NULLS LAST,
                 MIN(first_time) NULLS LAST,
                 segment_id
        """,
        (),
        simplify=False,
    ) or []


def _archive_stats():
    summary = db_query(
        """
        SELECT (SELECT SUM(nimages)::BIGINT FROM image_stats_site) AS total_images,
               (SELECT COUNT(DISTINCT night)::BIGINT FROM image_stats_daily_site) AS total_nights,
               (SELECT MIN(first_time) FROM image_stats_site) AS first_time,
               (SELECT MAX(last_time) FROM image_stats_site) AS last_time,
               (SELECT MIN(first_night) FROM image_stats_site) AS first_night,
               (SELECT MAX(last_night) FROM image_stats_site) AS last_night
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
            "target_classes": _target_class_distribution(),
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
