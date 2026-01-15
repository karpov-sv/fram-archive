"""
Data helpers for Locust load testing

Utilities for selecting test data, generating random parameters, etc.
"""
import random
import os
from typing import List, Dict, Optional


# Django ORM support for localhost testing
_DJANGO_AVAILABLE = False
_DJANGO_IMAGES_MODEL = None

def _init_django():
    """Initialize Django ORM if available (for localhost testing)"""
    global _DJANGO_AVAILABLE, _DJANGO_IMAGES_MODEL

    if _DJANGO_AVAILABLE or _DJANGO_IMAGES_MODEL:
        return  # Already initialized

    try:
        # Only try to import Django if we're likely on localhost
        # Check if DJANGO_SETTINGS_MODULE is set or we can find settings
        if 'DJANGO_SETTINGS_MODULE' not in os.environ:
            os.environ["DJANGO_SETTINGS_MODULE"] = "archive.settings"

        import django
        django.setup()
        from archive import models

        _DJANGO_IMAGES_MODEL = models.Images
        _DJANGO_AVAILABLE = True
        print("✓ Django ORM initialized - using real image IDs from database")
    except Exception as e:
        # Django not available or can't connect to DB - use fallback
        _DJANGO_AVAILABLE = False
        print(f"✗ Django ORM not available ({e.__class__.__name__}) - using random image IDs")


def _fetch_real_image_ids(count: int = 100) -> Optional[List[int]]:
    """
    Fetch real image IDs from database using Django ORM

    Args:
        count: Number of IDs to fetch

    Returns:
        List of image IDs or None if Django not available
    """
    if not _DJANGO_AVAILABLE:
        _init_django()

    if not _DJANGO_AVAILABLE or _DJANGO_IMAGES_MODEL is None:
        return None

    try:
        # Fetch random images from database
        images = _DJANGO_IMAGES_MODEL.objects.order_by('?')[:count].values_list('id', flat=True)
        ids = list(images)

        if ids:
            print(f"✓ Fetched {len(ids)} real image IDs from database (range: {min(ids)}-{max(ids)})")
            return ids
        else:
            print("✗ No images found in database - using random IDs")
            return None
    except Exception as e:
        print(f"✗ Failed to fetch image IDs from database ({e.__class__.__name__}) - using random IDs")
        return None


def _is_localhost(host: Optional[str] = None) -> bool:
    """
    Check if we're running against localhost

    Checks both LOCUST_HOST environment variable and the configured environment
    from locust_tests/config/environments.py. LOCUST_HOST takes precedence.

    Args:
        host: Host URL to check (defaults to auto-detection)

    Returns:
        True if host is localhost
    """
    def _check_host(h: str) -> bool:
        """Helper to check if a host string is localhost"""
        h = h.lower()
        return 'localhost' in h or '127.0.0.1' in h or h.startswith('http://0.0.0.0')

    # Check explicitly provided host
    if host is not None:
        return _check_host(host)

    # Check LOCUST_HOST environment variable (highest priority)
    env_host = os.getenv('LOCUST_HOST', '')
    if env_host:
        return _check_host(env_host)

    # Check configured environment from environments.py
    try:
        from locust_tests.config.environments import get_environment
        env = get_environment()
        if env and env.host:
            return _check_host(env.host)
    except Exception:
        # If we can't import or get environment, assume not localhost
        pass

    return False


class ImageDataHelper:
    """Helper for selecting image IDs and parameters"""

    def __init__(self, id_range: tuple = (1, 10000)):
        """
        Initialize with image ID range

        Args:
            id_range: Tuple of (min_id, max_id)
        """
        self.min_id, self.max_id = id_range
        self._cached_ids = None

    def get_random_id(self) -> int:
        """Get random image ID from range"""
        return random.randint(self.min_id, self.max_id)

    def get_random_ids(self, count: int = 10) -> List[int]:
        """
        Get list of random image IDs

        Args:
            count: Number of IDs to generate

        Returns:
            List of random image IDs
        """
        return [self.get_random_id() for _ in range(count)]

    def cache_ids(self, ids: List[int]):
        """
        Cache a list of valid image IDs

        Args:
            ids: List of valid image IDs from database
        """
        self._cached_ids = ids

    def get_cached_id(self) -> Optional[int]:
        """Get random ID from cached list"""
        if self._cached_ids:
            return random.choice(self._cached_ids)
        return self.get_random_id()


class TargetDataHelper:
    """Helper for astronomical target coordinates"""

    # Common astronomical targets for testing
    TARGETS = [
        {'name': 'M31', 'ra': 10.68, 'dec': 41.27, 'description': 'Andromeda Galaxy'},
        {'name': 'M42', 'ra': 83.82, 'dec': -5.39, 'description': 'Orion Nebula'},
        {'name': 'M45', 'ra': 56.75, 'dec': 24.12, 'description': 'Pleiades'},
        {'name': 'M51', 'ra': 202.47, 'dec': 47.20, 'description': 'Whirlpool Galaxy'},
        {'name': 'M13', 'ra': 250.42, 'dec': 36.46, 'description': 'Hercules Cluster'},
        {'name': 'M27', 'ra': 299.90, 'dec': 22.72, 'description': 'Dumbbell Nebula'},
        {'name': 'M57', 'ra': 283.40, 'dec': 33.03, 'description': 'Ring Nebula'},
        {'name': 'NGC2244', 'ra': 98.21, 'dec': 4.95, 'description': 'Rosette Nebula'},
        {'name': 'NGC7000', 'ra': 312.83, 'dec': 44.33, 'description': 'North America Nebula'},
        {'name': 'Polaris', 'ra': 37.95, 'dec': 89.26, 'description': 'North Star'},
    ]

    @staticmethod
    def get_random_target() -> Dict:
        """Get random astronomical target"""
        return random.choice(TargetDataHelper.TARGETS)

    @staticmethod
    def get_target_by_name(name: str) -> Optional[Dict]:
        """
        Get target by name

        Args:
            name: Target name (e.g., 'M31')

        Returns:
            Target dict or None if not found
        """
        for target in TargetDataHelper.TARGETS:
            if target['name'].upper() == name.upper():
                return target
        return None

    @staticmethod
    def get_random_coordinates() -> tuple:
        """
        Get random sky coordinates

        Returns:
            Tuple of (ra, dec)
        """
        ra = random.uniform(0, 360)
        dec = random.uniform(-90, 90)
        return ra, dec


class SearchParameterHelper:
    """Helper for generating search parameters"""

    SITES = ['S104', 'S105', 'S106', 'all']
    FILTERS = ['B', 'V', 'R', 'I', 'z', 'all']
    TYPES = ['survey', 'followup', 'calibration', 'test', 'all']
    CCDS = ['WF1', 'WF2', 'NF1', 'NF2', 'all']

    @staticmethod
    def get_random_site() -> str:
        """Get random site"""
        return random.choice(SearchParameterHelper.SITES)

    @staticmethod
    def get_random_filter() -> str:
        """Get random filter"""
        return random.choice(SearchParameterHelper.FILTERS)

    @staticmethod
    def get_random_type() -> str:
        """Get random image type"""
        return random.choice(SearchParameterHelper.TYPES)

    @staticmethod
    def get_random_ccd() -> str:
        """Get random CCD"""
        return random.choice(SearchParameterHelper.CCDS)

    @staticmethod
    def get_random_night_range() -> tuple:
        """
        Get random night range for filtering

        Returns:
            Tuple of (night1, night2) as YYYYMMDD strings
        """
        year = random.randint(2018, 2024)
        month1 = random.randint(1, 12)
        month2 = random.randint(month1, 12)

        night1 = f"{year}{month1:02d}01"
        night2 = f"{year}{month2:02d}28"

        return night1, night2

    @staticmethod
    def get_random_search_params() -> Dict:
        """
        Get random search parameters

        Returns:
            Dict with random search parameters
        """
        params = {}

        # Add site (80% chance)
        if random.random() < 0.8:
            params['site'] = SearchParameterHelper.get_random_site()

        # Add filter (70% chance)
        if random.random() < 0.7:
            params['filter'] = SearchParameterHelper.get_random_filter()

        # Add type (50% chance)
        if random.random() < 0.5:
            params['type'] = SearchParameterHelper.get_random_type()

        # Add night range (40% chance)
        if random.random() < 0.4:
            night1, night2 = SearchParameterHelper.get_random_night_range()
            params['night1'] = night1
            params['night2'] = night2

        return params


class SearchRadiusHelper:
    """Helper for search radius values"""

    @staticmethod
    def get_search_radius(mode: str = 'normal') -> tuple:
        """
        Get search radius with units

        Args:
            mode: 'tight' (arcsec), 'normal' (arcmin), 'wide' (degrees)

        Returns:
            Tuple of (value, units)
        """
        if mode == 'tight':
            return random.uniform(5, 30), 'arcsec'
        elif mode == 'wide':
            return random.uniform(0.5, 2.0), 'deg'
        else:  # normal
            return random.uniform(1, 10), 'arcmin'

    @staticmethod
    def get_cutout_radius() -> float:
        """Get cutout radius in degrees (0.01 - 0.5)"""
        return random.uniform(0.01, 0.5)

    @staticmethod
    def get_photometry_radius() -> float:
        """Get photometry search radius in degrees (0.001 - 0.05)"""
        return random.uniform(0.001, 0.05)


def get_random_image_ids(count: int = 100, id_range: tuple = (1, 10000), force_db: bool = False) -> List[int]:
    """
    Get list of random image IDs

    On localhost (or if force_db=True), fetches real IDs from database via Django ORM.
    Otherwise, generates random IDs from id_range.

    Args:
        count: Number of IDs to generate
        id_range: Tuple of (min_id, max_id) - used as fallback if DB not available
        force_db: Force database fetch even if not on localhost

    Returns:
        List of random image IDs
    """
    # Try to fetch real IDs from database if on localhost or forced
    if force_db or _is_localhost():
        real_ids = _fetch_real_image_ids(count)
        if real_ids:
            return real_ids

    # Fallback to random IDs
    helper = ImageDataHelper(id_range)
    return helper.get_random_ids(count)


def get_random_target() -> Dict:
    """Get random astronomical target - convenience function"""
    return TargetDataHelper.get_random_target()
