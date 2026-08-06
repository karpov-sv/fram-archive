"""
Pytest configuration and shared fixtures for performance testing
"""
import pytest
import time
import os
from contextlib import contextmanager
from decouple import Config, RepositoryEnv

import django
from django.conf import settings
from django.test import Client
from django.core.cache import cache
from django.db import connection


# Load configuration from .env.test file
config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env.test')
config = Config(RepositoryEnv(config_file))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archive.settings')
django.setup()


@pytest.fixture(scope="session")
def django_db_setup():
    """Setup Django database for testing"""
    settings.DEBUG = True  # Enable query logging


@pytest.fixture(scope="session")
def django_db_modify_db_settings():
    """Allow access to the 'fram' database in tests"""
    from django.conf import settings as django_settings
    # Configure the fram database for testing - use the same database as production
    # since it's read-only
    if 'fram' in django_settings.DATABASES:
        django_settings.DATABASES['fram']['TEST'] = {
            'NAME': django_settings.DATABASES['fram']['NAME']
        }


@pytest.fixture
def client(django_db_blocker):
    """
    Django test client with authentication
    """
    client = Client()

    # Get credentials from environment
    username = config('TEST_USERNAME', default='test_user')
    password = config('TEST_PASSWORD', default='test_password')

    with django_db_blocker.unblock():
        # Attempt login
        login_response = client.post('/login/', {
            'username': username,
            'password': password,
        }, follow=True)

        # Store credentials for reference
        client.test_username = username
        client.is_authenticated = (login_response.status_code == 200)

    return client


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before and after each test"""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def performance_timer():
    """
    Fixture to measure execution time

    Usage:
        with performance_timer() as get_time:
            # ... code to measure ...
            pass
        elapsed = get_time()
    """
    return measure_time


@contextmanager
def measure_time():
    """
    Context manager to measure execution time in seconds

    Returns:
        Callable that returns elapsed time when called
    """
    start = time.perf_counter()

    def get_elapsed():
        return time.perf_counter() - start

    yield get_elapsed


@contextmanager
def assert_query_count(expected_count, tolerance=0, database='all'):
    """
    Context manager to assert database query count

    Args:
        expected_count: Expected number of queries
        tolerance: Allowed deviation from expected count
        database: Which database to track ('default', 'fram', or 'all')

    Yields a record which, once the block is over, holds the queries that were
    made and how many of them there were, for a test that has something to say
    about them beyond their number.

    Usage:
        with assert_query_count(2, tolerance=1):
            # Code that should make 1-3 queries
            obj = Model.objects.get(id=1)
    """
    from django.db import connections

    # Enable query logging
    settings.DEBUG = True

    # Track queries on specified databases
    if database == 'all':
        dbs_to_track = ['default', 'fram']
    else:
        dbs_to_track = [database]

    # Reset queries and store initial counts
    queries_before = {}
    for db_name in dbs_to_track:
        if db_name in connections:
            conn = connections[db_name]
            if hasattr(conn, 'queries_log'):
                conn.queries_log.clear()
            queries_before[db_name] = len(conn.queries)

    record = {'count': None, 'queries': []}

    yield record

    # Count queries after execution
    queries_after = {}
    all_queries = []
    for db_name in dbs_to_track:
        if db_name in connections:
            conn = connections[db_name]
            queries_after[db_name] = len(conn.queries)
            before = queries_before.get(db_name, 0)
            after = queries_after.get(db_name, 0)
            if after > before:
                all_queries.extend(conn.queries[before:after])

    actual_count = sum(queries_after.get(db, 0) - queries_before.get(db, 0)
                       for db in dbs_to_track if db in queries_before)

    record['count'] = actual_count
    record['queries'] = all_queries

    assert abs(actual_count - expected_count) <= tolerance, \
        f"Expected {expected_count}±{tolerance} queries, got {actual_count}. " \
        f"Queries: {all_queries}"


@contextmanager
def assert_time_under(max_seconds, description="Operation"):
    """
    Context manager to assert operation completes within time limit

    Args:
        max_seconds: Maximum allowed time in seconds
        description: Description of operation for error message

    Usage:
        with assert_time_under(0.5, "Image preview"):
            response = client.get('/images/1/preview')
    """
    start = time.perf_counter()

    yield

    elapsed = time.perf_counter() - start

    assert elapsed < max_seconds, \
        f"{description} took {elapsed:.3f}s, expected <{max_seconds}s"


@pytest.fixture
def test_image_id(django_db_blocker):
    """
    Return a valid test image ID

    Returns first image from database, or None if no images exist
    """
    from archive.models import Images

    with django_db_blocker.unblock():
        first_image = Images.objects.first()
        return first_image.id if first_image else None


@pytest.fixture
def test_image(django_db_blocker):
    """
    Return a test image object

    Returns first image from database
    """
    from archive.models import Images

    with django_db_blocker.unblock():
        first_image = Images.objects.first()

        if not first_image:
            pytest.skip("No images in database for testing")

        return first_image


@pytest.fixture
def test_coordinates():
    """
    Return test sky coordinates for spatial queries

    Returns dict with ra, dec, sr (search radius)
    """
    return {
        'ra': 10.68,   # M31 approximate RA
        'dec': 41.27,  # M31 approximate Dec
        'sr': 0.01,    # 0.01 degrees search radius
        'name': 'M31'
    }


def photometry_params(coordinates, **extra):
    """
    Query parameters of a photometry cone search

    get_lc() takes any mapping of them - request.GET in a view, a plain dict
    here - and this is the smallest one that describes a search.
    """
    params = {
        'ra': coordinates['ra'],
        'dec': coordinates['dec'],
        'sr': coordinates['sr'],
    }
    params.update(extra)

    return params


@pytest.fixture
def multiple_test_images(django_db_blocker):
    """
    Return multiple test image IDs for batch operations

    Returns list of up to 10 image IDs
    """
    from archive.models import Images

    with django_db_blocker.unblock():
        images = Images.objects.all()[:10]
        ids = [img.id for img in images]

        if not ids:
            pytest.skip("No images in database for testing")

        return ids


@pytest.fixture
def calibration_test_params(test_image):
    """
    Return parameters for testing calibration lookup

    Returns dict with image and calibration type
    """
    return {
        'image': test_image,
        'type': 'masterdark'
    }


def pytest_configure(config):
    """
    Configure pytest with custom markers
    """
    config.addinivalue_line(
        "markers", "performance: mark test as a performance test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running (>10 seconds)"
    )
    config.addinivalue_line(
        "markers", "cache: mark test as cache-related"
    )
    config.addinivalue_line(
        "markers", "query: mark test as database query test"
    )


@pytest.fixture
def benchmark_metrics():
    """
    Fixture to collect performance metrics during tests

    Returns dict to store metrics
    """
    metrics = {
        'query_count': 0,
        'cache_hits': 0,
        'cache_misses': 0,
        'response_times': [],
    }
    return metrics


# Helper functions for tests

def get_cache_key(func_name, *args, **kwargs):
    """
    Generate cache key in the same format as memoize decorator

    Used to verify cache keys in tests
    """
    import hashlib
    import pickle

    key_data = (func_name, args, kwargs)
    key = f"{func_name}:{hashlib.md5(pickle.dumps(key_data)).hexdigest()}"
    return key
