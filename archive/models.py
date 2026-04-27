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
    image = models.IntegerField(blank=True, null=True)
    night = models.TextField(blank=True, null=True)
    time = models.DateTimeField(primary_key=True)
    filter = models.TextField(blank=True, null=True)
    ccd = models.TextField(blank=True, null=True)
    site = models.TextField(blank=True, null=True)
    ra = models.FloatField(blank=True, null=True)
    dec = models.FloatField(blank=True, null=True)
    mag = models.FloatField(blank=True, null=True)
    magerr = models.FloatField(blank=True, null=True)
    flags = models.FloatField(blank=True, null=True)
    fwhm = models.FloatField(blank=True, null=True)
    std = models.FloatField(blank=True, null=True)
    nstars = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'photometry'
        app_label = 'fram'
