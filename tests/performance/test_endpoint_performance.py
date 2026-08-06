"""
Endpoint Performance Tests

Tests response time thresholds for all endpoints by category:
- Fast endpoints: <500ms
- Medium endpoints: 0.5-2s
- Expensive endpoints: 1-5s
- Very expensive endpoints: 5-20s
"""
import pytest
import time
import numpy as np
import os

from tests.conftest import assert_time_under


def run_synthetic_preview_benchmark(
    client,
    test_image_id,
    monkeypatch,
    path,
    label,
):
    from archive import views_images

    synthetic_size = 4096
    rng = np.random.default_rng(0)
    synthetic_data = rng.normal(
        loc=1000.0,
        scale=100.0,
        size=(synthetic_size, synthetic_size),
    ).astype(np.float32)
    synthetic_header = {}

    def fake_getdata(filename, ext):
        return synthetic_data

    def fake_getheader(filename, ext):
        return synthetic_header

    def fake_crop_overscans(data, header, subtract=True, cfg=None):
        return data, header

    monkeypatch.setattr(views_images.fits, "getdata", fake_getdata)
    monkeypatch.setattr(views_images.fits, "getheader", fake_getheader)
    monkeypatch.setattr(views_images.calibrate, "crop_overscans", fake_crop_overscans)

    iterations = int(os.getenv("PREVIEW_BENCH_ITERS", "1"))
    durations = []
    response = None

    for _ in range(iterations):
        start = time.perf_counter()
        response = client.get(path, {"raw": "1"})
        durations.append(time.perf_counter() - start)

    mean_ms = (sum(durations) / len(durations)) * 1000.0
    print(f"\n{label} x{iterations}: {mean_ms:.1f}ms mean")

    assert response is not None and response.status_code == 200


@pytest.mark.performance
@pytest.mark.django_db(databases=['fram', 'default'])
class TestFastEndpoints:
    """Fast endpoints should respond in <500ms"""

    @pytest.mark.parametrize("endpoint,description", [
        ("/", "Index page"),
        ("/nights/", "Nights browser"),
    ])
    def test_fast_navigation_endpoints(self, client, endpoint, description):
        """Navigation endpoints should be fast"""
        start = time.perf_counter()
        response = client.get(endpoint)
        elapsed = time.perf_counter() - start

        print(f"\n{description} ({endpoint}): {elapsed*1000:.1f}ms")

        assert response.status_code in [200, 302], \
            f"{description} returned {response.status_code}"
        assert elapsed < 0.5, \
            f"{description} took {elapsed:.3f}s, expected <0.5s"

    def test_cached_preview_fast(self, client, test_image_id):
        """Cached image preview should be fast"""
        if test_image_id is None:
            pytest.skip("No test image available")

        endpoint = f"/images/{test_image_id}/preview"

        # First request - warm cache
        client.get(endpoint)

        # Second request - should be cached
        start = time.perf_counter()
        response = client.get(endpoint)
        elapsed = time.perf_counter() - start

        print(f"\nCached preview: {elapsed*1000:.1f}ms")

        assert response.status_code == 200
        assert elapsed < 0.5, \
            f"Cached preview took {elapsed:.3f}s, expected <0.5s"

    def test_cached_view_fast(self, client, test_image_id):
        """Cached image view should be fast"""
        if test_image_id is None:
            pytest.skip("No test image available")

        endpoint = f"/images/{test_image_id}/view"

        # First request - warm cache
        client.get(endpoint)

        # Second request - should be cached
        start = time.perf_counter()
        response = client.get(endpoint)
        elapsed = time.perf_counter() - start

        print(f"\nCached view: {elapsed*1000:.1f}ms")

        assert response.status_code == 200
        assert elapsed < 0.5, \
            f"Cached view took {elapsed:.3f}s, expected <0.5s"


@pytest.mark.performance
@pytest.mark.django_db(databases=['fram', 'default'])
class TestMediumEndpoints:
    """Medium endpoints should respond in 0.5-2s"""

    def test_image_list(self, client):
        """Image list with filters"""
        start = time.perf_counter()
        response = client.get('/images/', {
            'site': 'S104',
            'filter': 'V'
        })
        elapsed = time.perf_counter() - start

        print(f"\nImage list: {elapsed*1000:.1f}ms")

        assert response.status_code in [200, 302]
        assert elapsed < 2.0, \
            f"Image list took {elapsed:.3f}s, expected <2s"

    def test_search_page(self, client):
        """Search page load"""
        start = time.perf_counter()
        response = client.get('/search/')
        elapsed = time.perf_counter() - start

        print(f"\nSearch page: {elapsed*1000:.1f}ms")

        assert response.status_code == 200
        assert elapsed < 2.0, \
            f"Search page took {elapsed:.3f}s, expected <2s"

    def test_image_details(self, client, test_image_id):
        """Image details page"""
        if test_image_id is None:
            pytest.skip("No test image available")

        start = time.perf_counter()
        response = client.get(f'/images/{test_image_id}/')
        elapsed = time.perf_counter() - start

        print(f"\nImage details: {elapsed*1000:.1f}ms")

        assert response.status_code == 200
        assert elapsed < 2.0, \
            f"Image details took {elapsed:.3f}s, expected <2s"

    def test_cutouts_list(self, client, test_coordinates):
        """Cutouts list with spatial query"""
        start = time.perf_counter()
        response = client.get('/images/cutouts/', {
            'ra': test_coordinates['ra'],
            'dec': test_coordinates['dec'],
            'sr': 0.5
        })
        elapsed = time.perf_counter() - start

        print(f"\nCutouts list: {elapsed*1000:.1f}ms")

        assert response.status_code == 200
        assert elapsed < 2.0, \
            f"Cutouts list took {elapsed:.3f}s, expected <2s"

    def test_photometry_json(self, client, test_coordinates):
        """Photometry JSON export"""
        start = time.perf_counter()
        response = client.get('/photometry/json', {
            'ra': test_coordinates['ra'],
            'dec': test_coordinates['dec'],
            'sr': 0.01
        })
        elapsed = time.perf_counter() - start

        print(f"\nPhotometry JSON: {elapsed*1000:.1f}ms")

        assert response.status_code == 200
        assert elapsed < 2.0, \
            f"Photometry JSON took {elapsed:.3f}s, expected <2s"


@pytest.mark.performance
@pytest.mark.django_db(databases=['fram', 'default'])
class TestExpensiveEndpoints:
    """Expensive endpoints should respond in 1-5s"""

    def test_full_image_uncached(self, client, test_image_id):
        """Full resolution image (first request)"""
        if test_image_id is None:
            pytest.skip("No test image available")

        # Clear cache to ensure cold start
        from django.core.cache import cache
        cache.clear()

        start = time.perf_counter()
        response = client.get(f'/images/{test_image_id}/full')
        elapsed = time.perf_counter() - start

        print(f"\nFull image (uncached): {elapsed:.3f}s")

        assert response.status_code == 200
        assert elapsed < 5.0, \
            f"Full image took {elapsed:.3f}s, expected <5s"

    def test_background_analysis(self, client, test_image_id):
        """Background analysis"""
        if test_image_id is None:
            pytest.skip("No test image available")

        from django.core.cache import cache
        cache.clear()

        start = time.perf_counter()
        response = client.get(f'/images/{test_image_id}/bg')
        elapsed = time.perf_counter() - start

        print(f"\nBackground analysis: {elapsed:.3f}s")

        assert response.status_code == 200
        assert elapsed < 5.0, \
            f"Background analysis took {elapsed:.3f}s, expected <5s"

    def test_fwhm_analysis(self, client, test_image_id):
        """FWHM analysis"""
        if test_image_id is None:
            pytest.skip("No test image available")

        from django.core.cache import cache
        cache.clear()

        start = time.perf_counter()
        response = client.get(f'/images/{test_image_id}/fwhm')
        elapsed = time.perf_counter() - start

        print(f"\nFWHM analysis: {elapsed:.3f}s")

        assert response.status_code == 200
        assert elapsed < 5.0, \
            f"FWHM analysis took {elapsed:.3f}s, expected <5s"

    def test_photometry_lightcurve(self, client, test_coordinates):
        """Photometry light curve plot"""
        start = time.perf_counter()
        response = client.get('/photometry/lc', {
            'ra': test_coordinates['ra'],
            'dec': test_coordinates['dec'],
            'sr': 0.01
        })
        elapsed = time.perf_counter() - start

        print(f"\nPhotometry light curve: {elapsed:.3f}s")

        assert response.status_code == 200
        assert elapsed < 5.0, \
            f"Light curve took {elapsed:.3f}s, expected <5s"

    def test_cutout_generation(self, client, test_image_id, test_coordinates):
        """Cutout generation"""
        if test_image_id is None:
            pytest.skip("No test image available")

        from django.core.cache import cache
        cache.clear()

        # The test image need not cover the test coordinates, and asking for a
        # cutout of a position that is not on the frame fails inside the WCS
        # inversion. That is the 500 allowed for below, so the exception has to
        # be turned into one rather than re-raised out of the client.
        raising = client.raise_request_exception
        client.raise_request_exception = False

        try:
            start = time.perf_counter()
            response = client.get(f'/images/{test_image_id}/cutout', {
                'ra': test_coordinates['ra'],
                'dec': test_coordinates['dec'],
                'sr': 0.1
            })
            elapsed = time.perf_counter() - start
        finally:
            client.raise_request_exception = raising

        print(f"\nCutout generation: {elapsed:.3f}s")

        # May return 500 if image doesn't overlap coordinates
        assert response.status_code in [200, 500]
        if response.status_code == 200:
            assert elapsed < 5.0, \
                f"Cutout generation took {elapsed:.3f}s, expected <5s"


@pytest.mark.performance
@pytest.mark.slow
@pytest.mark.django_db(databases=['fram', 'default'])
class TestSyntheticImagePreview:
    """Benchmark image_preview without FITS I/O using synthetic data"""

    def test_image_preview_raw_synthetic_full(self, client, test_image_id, monkeypatch):
        """Raw preview path with synthetic 4096x4096 image"""
        if test_image_id is None:
            pytest.skip("No test image available")

        path = f"/images/{test_image_id}/full"
        run_synthetic_preview_benchmark(
            client,
            test_image_id,
            monkeypatch,
            path,
            "Synthetic raw full preview (4096x4096)",
        )

    def test_image_preview_raw_synthetic_view(self, client, test_image_id, monkeypatch):
        """Raw view path with synthetic 4096x4096 image"""
        if test_image_id is None:
            pytest.skip("No test image available")

        path = f"/images/{test_image_id}/view"
        run_synthetic_preview_benchmark(
            client,
            test_image_id,
            monkeypatch,
            path,
            "Synthetic raw view preview (800px)",
        )

    def test_image_preview_raw_synthetic_preview(self, client, test_image_id, monkeypatch):
        """Raw preview path with synthetic 4096x4096 image"""
        if test_image_id is None:
            pytest.skip("No test image available")

        path = f"/images/{test_image_id}/preview"
        run_synthetic_preview_benchmark(
            client,
            test_image_id,
            monkeypatch,
            path,
            "Synthetic raw preview (128px)",
        )


@pytest.mark.performance
@pytest.mark.slow
@pytest.mark.django_db(databases=['fram', 'default'])
class TestVeryExpensiveEndpoints:
    """Very expensive endpoints should respond in 5-20s"""

    def test_wcs_verification(self, client, test_image_id):
        """WCS verification (very expensive)"""
        if test_image_id is None:
            pytest.skip("No test image available")

        from django.core.cache import cache
        cache.clear()

        start = time.perf_counter()
        response = client.get(f'/images/{test_image_id}/wcs')
        elapsed = time.perf_counter() - start

        print(f"\nWCS verification: {elapsed:.3f}s")

        assert response.status_code in [200, 500]
        if response.status_code == 200:
            assert elapsed < 20.0, \
                f"WCS verification took {elapsed:.3f}s, expected <20s"

    def test_photometric_calibration(self, client, test_image_id):
        """Photometric zero point calibration (very expensive)"""
        if test_image_id is None:
            pytest.skip("No test image available")

        from django.core.cache import cache
        cache.clear()

        start = time.perf_counter()
        response = client.get(f'/images/{test_image_id}/zero')
        elapsed = time.perf_counter() - start

        print(f"\nPhotometric calibration: {elapsed:.3f}s")

        assert response.status_code in [200, 500]
        if response.status_code == 200:
            assert elapsed < 20.0, \
                f"Photometric calibration took {elapsed:.3f}s, expected <20s"

    def test_filter_analysis(self, client, test_image_id):
        """Multi-filter color analysis (very expensive)"""
        if test_image_id is None:
            pytest.skip("No test image available")

        from django.core.cache import cache
        cache.clear()

        start = time.perf_counter()
        response = client.get(f'/images/{test_image_id}/filters')
        elapsed = time.perf_counter() - start

        print(f"\nFilter analysis: {elapsed:.3f}s")

        assert response.status_code in [200, 500]
        if response.status_code == 200:
            assert elapsed < 20.0, \
                f"Filter analysis took {elapsed:.3f}s, expected <20s"


@pytest.mark.performance
@pytest.mark.django_db(databases=['fram', 'default'])
class TestCacheImprovement:
    """Verify caching improves performance"""

    def test_preview_cache_improvement(self, client, test_image_id):
        """Preview should be much faster when cached"""
        if test_image_id is None:
            pytest.skip("No test image available")

        from django.core.cache import cache
        cache.clear()

        endpoint = f"/images/{test_image_id}/preview"

        # First request - cold
        start = time.perf_counter()
        response1 = client.get(endpoint)
        cold_time = time.perf_counter() - start

        # Second request - cached
        start = time.perf_counter()
        response2 = client.get(endpoint)
        cached_time = time.perf_counter() - start

        print(f"\nPreview cold: {cold_time*1000:.1f}ms")
        print(f"Preview cached: {cached_time*1000:.1f}ms")
        print(f"Improvement: {cold_time/cached_time:.1f}x")

        assert response1.status_code == 200
        assert response2.status_code == 200

        # Cached should be faster
        assert cached_time < cold_time, \
            "Cached request should be faster than cold request"

        # Cached should be very fast
        assert cached_time < 0.5, \
            f"Cached preview took {cached_time:.3f}s, expected <0.5s"
