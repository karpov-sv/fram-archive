# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey has `on_delete` set to the desired behavior.
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.

from django.core.cache import cache
from django.db import models
from django.db.models import JSONField
from django.db.models.query import QuerySet
from django.utils import timezone
from django_fast_count.managers import FastCountManager, FastCountQuerySet
from datetime import timedelta
from collections import namedtuple


class CacheOnlyFastCountQuerySet(FastCountQuerySet):
    """FastCountQuerySet variant that uses only Django's cache layer.

    Why: the FastCount bookkeeping table lives in the 'default' DB but the
    Images model is routed to 'fram' (PostgreSQL, read-only, externally
    managed), so any FastCount.objects.using(self.db) call fails. This
    subclass skips the DB fallback while keeping cache-based memoization.
    """

    def count(self):
        cache_key = self._get_cache_key()
        cached = cache.get(cache_key)
        if cached is not None:
            self.maybe_trigger_precache()
            return cached

        actual = QuerySet(model=self.model, query=self.query.clone(), using=self.db).count()
        self.maybe_trigger_precache()

        if actual >= self.cache_counts_larger_than:
            expires_seconds = int(self.expire_cached_counts_after.total_seconds())
            if expires_seconds > 0:
                cache.set(cache_key, actual, expires_seconds)
        return actual

    def precache_counts(self):
        expires_seconds = int(self.expire_cached_counts_after.total_seconds())
        results = {}
        for qs in self.get_precache_querysets():
            key = self._get_cache_key(qs)
            try:
                actual = QuerySet(model=qs.model, query=qs.query.clone(), using=qs.db).count()
                if expires_seconds > 0:
                    cache.set(key, actual, expires_seconds)
                results[key] = actual
            except Exception as e:
                results[key] = f"Error: {e}"
        return results


class CacheOnlyFastCountManager(FastCountManager):
    def get_queryset(self):
        return CacheOnlyFastCountQuerySet(manager_instance=self)


class Images(models.Model):
    id = models.IntegerField(primary_key=True)
    filename = models.TextField(unique=True, blank=True, null=True)
    night = models.TextField(blank=True, null=True)
    time = models.DateTimeField(blank=True, null=True)
    target = models.IntegerField(blank=True, null=True)
    type = models.TextField(blank=True, null=True)
    filter = models.TextField(blank=True, null=True)
    exposure = models.FloatField(blank=True, null=True)
    ccd = models.TextField(blank=True, null=True)
    serial = models.IntegerField(blank=True, null=True)
    binning = models.TextField(blank=True, null=True)
    site = models.TextField(blank=True, null=True)
    ra = models.FloatField(blank=True, null=True)
    dec = models.FloatField(blank=True, null=True)
    radius = models.FloatField(blank=True, null=True)
    width = models.IntegerField(blank=True, null=True)
    height = models.IntegerField(blank=True, null=True)
    cropped_width = models.IntegerField(blank=True, null=True)
    cropped_height = models.IntegerField(blank=True, null=True)
    # footprints skipped
    mean = models.FloatField(blank=True, null=True)
    median = models.FloatField(blank=True, null=True)
    keywords = JSONField(blank=True, null=True)

    objects = CacheOnlyFastCountManager(
        precache_count_every=timedelta(hours=1),      # Default: 10 minutes
        cache_counts_larger_than=100_000,           # Default: 1,000,000
        expire_cached_counts_after=timedelta(hours=2), # Default: 10 minutes
        disable_forked_precaching=True,             # Optional: Defaults to False. Recommended: True for production.
    )

    class Meta:
        managed = False
        db_table = 'images'
        app_label = 'fram'


class Calibrations(models.Model):
    id = models.IntegerField(primary_key=True)
    filename = models.TextField(unique=True, blank=True, null=True)
    night = models.TextField(blank=True, null=True)
    time = models.DateTimeField(blank=True, null=True)
    target = models.IntegerField(blank=True, null=True)
    type = models.TextField(blank=True, null=True)
    filter = models.TextField(blank=True, null=True)
    exposure = models.FloatField(blank=True, null=True)
    ccd = models.TextField(blank=True, null=True)
    serial = models.IntegerField(blank=True, null=True)
    binning = models.TextField(blank=True, null=True)
    site = models.TextField(blank=True, null=True)
    ra = models.FloatField(blank=True, null=True)
    dec = models.FloatField(blank=True, null=True)
    radius = models.FloatField(blank=True, null=True)
    width = models.IntegerField(blank=True, null=True)
    height = models.IntegerField(blank=True, null=True)
    # footprints skipped
    mean = models.FloatField(blank=True, null=True)
    median = models.FloatField(blank=True, null=True)
    keywords = JSONField(blank=True, null=True)
    cropped_width = models.IntegerField(blank=True, null=True)
    cropped_height = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'calibrations'
        app_label = 'fram'


class Photometry(models.Model):
    image = models.ForeignKey(
        Images,
        models.DO_NOTHING,
        db_column='image',
        blank=True,
        null=True,
        related_name='+',
    )
    time = models.DateTimeField(primary_key=True)
    filter = models.TextField(blank=True, null=True)
    ra = models.FloatField(blank=True, null=True)
    dec = models.FloatField(blank=True, null=True)
    mag = models.FloatField(blank=True, null=True)
    magerr = models.FloatField(blank=True, null=True)
    flags = models.FloatField(blank=True, null=True)
    mag_color = models.FloatField(blank=True, null=True)
    color_term = models.FloatField(blank=True, null=True)
    fwhm = models.FloatField(blank=True, null=True)
    std = models.FloatField(blank=True, null=True)
    zp_std = models.FloatField(blank=True, null=True)
    nstars = models.FloatField(blank=True, null=True)
    final_frac = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'photometry_all'
        app_label = 'fram'


# `photometry_all` is a partitioned parent with one child table per (site, ccd).
# A cone search on the parent visits every child, which on cold cache costs a
# full round of index probes and heap reads even for a partition that cannot
# possibly hold matching rows. When the caller has narrowed the search to a
# single partition — either by giving both site and ccd, or by giving one that
# happens to be unique across the whole set — we route the query directly to
# the corresponding child.
#
# Keys are (normalised_site, normalised_ccd) where normalisation is: replace
# '-' with '_' in the site, lowercase the ccd. Update this map if a new
# partition is ingested; the values must name real tables in the `fram` DB.
PHOTOMETRY_PARTITIONS = {
    ('auger',  'nf3'): 'photometry_auger_nf3',
    ('auger',  'nf4'): 'photometry_auger_nf4',
    ('auger',  'wf4'): 'photometry_auger_wf4',
    ('auger',  'wf6'): 'photometry_auger_wf6',
    ('auger',  'wf7'): 'photometry_auger_wf7',
    ('auger',  'wf8'): 'photometry_auger_wf8',
    ('auger2', 'wf0'): 'photometry_auger2_wf0',
    ('cta_n',  'c0'):  'photometry_cta_n_c0',
    ('cta_n',  'wf0'): 'photometry_cta_n_wf0',
    ('cta_s0', 'wf0'): 'photometry_cta_s0_wf0',
    ('cta_s1', 'wf0'): 'photometry_cta_s1_wf0',
}

# Meta-group ccd tokens (as submitted by the form) mapped to the UNION-ALL
# view that spans the group's children. The view is the source of truth for
# which real ccds belong to which group — this Python side does not enumerate
# them, so the same ccd name could later appear in more than one group without
# any change here.
PHOTOMETRY_CCD_GROUPS = {
    'all_nf': 'photometry_all_nf',
    'all_wf': 'photometry_all_wf',
}


def _norm(kind, value):
    if not value or value == 'all':
        return None
    return value.replace('-', '_') if kind == 'site' else value.lower()


class PhotometryRoute(namedtuple('PhotometryRoute',
                                 ['table', 'narrows_site', 'narrows_ccd'])):
    """A routing decision for a photometry cone search.

    `table` is what to put in the FROM clause. The two flags say whether
    `table` already restricts rows to the caller's site / ccd on its own — a
    specific partition narrows both, a group view narrows only ccd, and the
    top-level parent narrows neither. The caller uses the flags to skip
    redundant WHERE clauses on the join to `images`.
    """
    __slots__ = ()


def photometry_route_for(site, ccd):
    """Route a search to the most specific photometry object that still holds
    every matching row.

    Routing paths, in order of precedence:
      * ccd is a meta-group token ('NF', 'WF') → the corresponding UNION-ALL
        view. If a site is also pinned, the view is still the right FROM (its
        member children span multiple sites but visiting only the group's
        subset beats visiting all 11 partitions); the caller keeps the site
        filter.
      * both site and ccd are concrete and name a real child → that child.
      * exactly one of site or ccd is given and appears in exactly one child
        → that child (e.g. ccd='NF4' pins `photometry_auger_nf4`).
      * everything else → the parent `photometry_all` with both filters left
        to the caller.
    """
    s = _norm('site', site)
    c = _norm('ccd', ccd)

    if c in PHOTOMETRY_CCD_GROUPS:
        return PhotometryRoute(PHOTOMETRY_CCD_GROUPS[c],
                               narrows_site=False, narrows_ccd=True)

    if s and c:
        t = PHOTOMETRY_PARTITIONS.get((s, c))
        if t:
            return PhotometryRoute(t, narrows_site=True, narrows_ccd=True)
        return PhotometryRoute('photometry_all', False, False)

    if s or c:
        matches = [t for (ps, pc), t in PHOTOMETRY_PARTITIONS.items()
                   if (s is None or ps == s) and (c is None or pc == c)]
        if len(matches) == 1:
            return PhotometryRoute(matches[0],
                                   narrows_site=True, narrows_ccd=True)

    return PhotometryRoute('photometry_all', False, False)
