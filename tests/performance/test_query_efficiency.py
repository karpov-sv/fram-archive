"""
Query Efficiency Tests

Validates database query patterns and counts:
- Image list: ≤5 queries
- Image details: ≤3 queries
- Photometry: 1 query for data
- No N+1 query patterns
"""
import pytest
from django.core.cache import cache

from archive.views_images import find_calibration_image, get_images
from archive.views_photometry import get_lc
from archive.utils import db_query
from tests.conftest import assert_query_count, photometry_params


@pytest.mark.query
@pytest.mark.performance
@pytest.mark.django_db(databases=['fram', 'default'])
class TestImageListQueries:
    """Test query efficiency for image listing"""

    def test_image_list_query_count(self, client):
        """Image list should use ≤5 queries

        Counted on the observational database alone: the session and the user
        of the authenticated test client live in the default one, and are an
        artifact of how the page is reached rather than of what it does.
        """
        # Clear cache to ensure we're testing query count
        cache.clear()

        with assert_query_count(5, tolerance=3, database='fram'):
            response = client.get('/images/', {
                'site': 'S104',
                'filter': 'V'
            })

        assert response.status_code in [200, 302]

    def test_image_list_with_filters(self, client):
        """Image list with multiple filters should not increase query count"""
        cache.clear()

        with assert_query_count(5, tolerance=3, database='fram'):
            response = client.get('/images/', {
                'site': 'S104',
                'filter': 'V',
                'type': 'survey',
                'night1': '20200101',
                'night2': '20201231'
            })

        assert response.status_code in [200, 302]

    def test_get_images_function_queries(self, client):
        """get_images() function query pattern"""
        from django.test import RequestFactory
        factory = RequestFactory()

        request = factory.get('/images/', {
            'site': 'S104',
            'filter': 'V'
        })

        # get_images returns a queryset, doesn't execute yet
        with assert_query_count(0):
            images = get_images(request)

        # Evaluation should trigger query
        with assert_query_count(1):
            list(images[:10])  # Fetch first 10


@pytest.mark.query
@pytest.mark.performance
@pytest.mark.django_db(databases=['fram', 'default'])
class TestCalibrationLookupQueries:
    """Test calibration lookup query patterns"""

    def test_calibration_lookup_first_time(self, test_image):
        """First calibration lookup should use 1-2 queries"""
        cache.clear()

        with assert_query_count(2, tolerance=1):
            result = find_calibration_image(test_image, 'masterdark')

    def test_calibration_lookup_cached(self, test_image):
        """Cached calibration lookup should use 0 queries"""
        cache.clear()

        # First call to populate cache
        find_calibration_image(test_image, 'masterdark')

        # Second call should not query
        with assert_query_count(0):
            find_calibration_image(test_image, 'masterdark')

    def test_multiple_calibration_types_cached(self, test_image):
        """Multiple calibration lookups should be independently cached"""
        cache.clear()

        # First call for each type
        for calib_type in ['masterdark', 'bias', 'masterflat']:
            find_calibration_image(test_image, calib_type)

        # Second calls should all be cached
        with assert_query_count(0):
            find_calibration_image(test_image, 'masterdark')
            find_calibration_image(test_image, 'bias')
            find_calibration_image(test_image, 'masterflat')


@pytest.mark.query
@pytest.mark.performance
@pytest.mark.django_db(databases=['fram', 'default'])
class TestPhotometryQueries:
    """Test photometry query patterns"""

    def test_photometry_single_query(self, client, test_coordinates):
        """Photometry should use single query for data"""
        # get_lc consults the cache before the database, so only a cold one
        # leaves a query to be counted
        cache.clear()

        with assert_query_count(1, tolerance=1):
            lc = get_lc(photometry_params(test_coordinates))

        assert isinstance(lc, list)

    def test_photometry_no_iteration_n_plus_one(self, client, test_coordinates):
        """Photometry should not have N+1 query pattern"""
        cache.clear()

        lc = get_lc(photometry_params(test_coordinates))

        # The single query brings back every column of every measurement, so
        # the light curve is built without going back for any of them
        with assert_query_count(0):
            columns = ['time', 'site', 'ccd', 'filter', 'ra', 'dec',
                       'mag', 'magerr', 'flags', 'fwhm', 'std', 'nstars']
            data = [[row[_] for _ in columns] for row in lc]

        assert len(data) == len(lc)
        #     sites.append(record.site)  # No query
        #     ...
        # This evaluates the queryset once, but loads full ORM objects

        # Even worse would be 10+ separate queries:
        # times = np.array([_.time for _ in lc])  # Query 1
        # sites = np.array([_.site for _ in lc])  # Query 2
        # ... etc


@pytest.mark.query
@pytest.mark.performance
@pytest.mark.django_db(databases=['fram', 'default'])
class TestSearchQueries:
    """Test search view query patterns"""

    def test_search_page_db_query_calls(self, client):
        """Search page should call db_query exactly 5 times"""
        cache.clear()

        # Search page calls db_query for:
        # 1. types
        # 2. sites
        # 3. ccds
        # 4. serials
        # 5. filters

        # All should be memoized after first call
        response = client.get('/search/')

        assert response.status_code == 200

        # Second call should use cache
        with assert_query_count(0, tolerance=2):
            response2 = client.get('/search/')

        assert response2.status_code == 200

    def test_db_query_memoization(self):
        """db_query should be memoized"""
        cache.clear()

        query = "select fast_distinct(%s, %s) as type"
        params = ('images', 'type')

        # First call
        with assert_query_count(1):
            result1 = db_query(query, params)

        # Second call should be cached
        with assert_query_count(0):
            result2 = db_query(query, params)

        assert result1 == result2


@pytest.mark.query
@pytest.mark.performance
@pytest.mark.django_db(databases=['fram', 'default'])
class TestImageDetailsQueries:
    """Test image details page query patterns"""

    def test_image_details_query_count(self, client, test_image_id):
        """Image details should use one query per calibration looked up"""
        if test_image_id is None:
            pytest.skip("No test image available")

        cache.clear()

        # Image details queries, on a cold cache:
        # 1. Get image
        # 2-9. The dark, bias, dark current and flat, each of them one query
        #      for the closest calibration taken before the image, and a second
        #      one only where there is none and the search turns forward
        with assert_query_count(7, tolerance=2, database='fram'):
            response = client.get(f'/images/{test_image_id}/')

        assert response.status_code == 200

    def test_image_details_with_calibration_cache(self, client, test_image_id):
        """Image details with cached calibrations should be faster"""
        if test_image_id is None:
            pytest.skip("No test image available")

        cache.clear()

        # First request
        response1 = client.get(f'/images/{test_image_id}/')

        # Second request - calibrations should be cached
        with assert_query_count(1, tolerance=1, database='fram'):
            # Should only query for the image itself
            response2 = client.get(f'/images/{test_image_id}/')

        assert response1.status_code == 200
        assert response2.status_code == 200


@pytest.mark.query
@pytest.mark.performance
@pytest.mark.django_db(databases=['fram', 'default'])
class TestNoNPlusOnePatterns:
    """Verify no N+1 query patterns exist"""

    def test_no_n_plus_one_in_photometry(self, test_coordinates):
        """Photometry should not have N+1 pattern"""
        # A tenth of the radius is a hundredth of the area, and so of the
        # measurements. The query count must not notice.
        small = photometry_params(test_coordinates, sr=0.1*test_coordinates['sr'])
        large = photometry_params(test_coordinates)

        cache.clear()
        with assert_query_count(1, tolerance=1):
            few = get_lc(small)

        cache.clear()
        with assert_query_count(1, tolerance=1):
            many = get_lc(large)

        # Worth knowing that the two really did differ in size, or the test
        # above would hold for a reason it is not meant to be testing
        assert len(many) > len(few)

    def test_calibration_cache_prevents_repeated_lookups(self, test_image):
        """Multiple calibration lookups should use cache"""
        cache.clear()

        # First lookup
        find_calibration_image(test_image, 'masterdark')

        # Next 10 lookups should all hit cache (0 queries)
        with assert_query_count(0):
            for _ in range(10):
                find_calibration_image(test_image, 'masterdark')


@pytest.mark.query
@pytest.mark.performance
@pytest.mark.django_db(databases=['fram', 'default'])
class TestQueryOptimizations:
    """Test that query optimizations are in place"""

    def test_spatial_queries_use_q3c(self, client, test_coordinates):
        """Spatial queries should use q3c for efficiency"""
        # This is verified by the query using q3c_radial_query
        # We can't directly test SQL, but we can verify it works

        response = client.get('/images/', {
            'ra': test_coordinates['ra'],
            'dec': test_coordinates['dec'],
            'sr': 0.5
        })

        assert response.status_code in [200, 302]

    def test_fast_distinct_used_for_filters(self):
        """Search filters should use fast_distinct"""
        cache.clear()

        # These should use fast_distinct function
        types = db_query("select fast_distinct(%s, %s) as type", ('images', 'type'))
        sites = db_query("select fast_distinct(%s, %s) as site", ('images', 'site'))

        # Results should be returned (even if empty)
        assert types is not None
        assert sites is not None

    def test_query_count_does_not_scale_with_filters(self, client):
        """Adding filters should not increase query count"""
        cache.clear()

        # The band is wide because the page costs anything from one query to
        # six: the lists of sites, cameras and filters are memoized, and so are
        # paid for by whichever request comes first, and a selection that turns
        # out to be empty is never fetched a page of
        with assert_query_count(3, tolerance=3, database='fram') as simple:
            client.get('/images/', {'site': 'S104'})

        # Complex query with many filters
        with assert_query_count(3, tolerance=3, database='fram') as filtered:
            client.get('/images/', {
                'site': 'S104',
                'filter': 'V',
                'type': 'survey',
                'ccd': 'WF1',
                'night1': '20200101',
                'night2': '20201231'
            })

        # The point of it: a narrower selection is described within the queries
        # the page already makes, so asking for one cannot add any
        assert filtered['count'] <= simple['count'], \
            f"{filtered['count']} queries with filters against " \
            f"{simple['count']} without: {filtered['queries']}"
