from django.apps import AppConfig


class ArchiveConfig(AppConfig):
    """Standard app config for the archive app."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'archive'


class FramConfig(AppConfig):
    """
    Virtual AppConfig for models with app_label='fram'.

    This allows models in archive/models.py to use app_label='fram'
    for clean separation of the PostgreSQL fram database, while
    avoiding 'No installed app with label' errors when caching
    model instances.

    This is a minimal config that just registers the 'fram' label
    without loading a separate models module.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'archive.apps.fram_virtual'  # Virtual module name
    label = 'fram'
    verbose_name = 'FRAM Database Models'

    def ready(self):
        # Don't import models - they're already loaded via ArchiveConfig
        pass
