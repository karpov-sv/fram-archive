"""
Data helpers for Locust load testing

Utilities for selecting test data, generating random parameters, etc.
"""
import random
from typing import List, Dict, Optional


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


def get_random_image_ids(count: int = 100, id_range: tuple = (1, 10000)) -> List[int]:
    """
    Get list of random image IDs

    Args:
        count: Number of IDs to generate
        id_range: Tuple of (min_id, max_id)

    Returns:
        List of random image IDs
    """
    helper = ImageDataHelper(id_range)
    return helper.get_random_ids(count)


def get_random_target() -> Dict:
    """Get random astronomical target - convenience function"""
    return TargetDataHelper.get_random_target()
