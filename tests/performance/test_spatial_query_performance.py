import os
import pytest

from django.db import utils as db_utils

from archive.models import Images
from tests.performance.spatial_query_benchmark import run_benchmark


@pytest.mark.performance
@pytest.mark.slow
@pytest.mark.django_db(databases=["fram", "default"])
class TestSpatialQueryBenchmark:
    def test_spatial_query_benchmark(self):
        iterations = int(os.getenv("SPATIAL_BENCH_ITERS", "30"))
        min_radius = float(os.getenv("SPATIAL_BENCH_MIN_RADIUS", "0.1"))
        max_radius = float(os.getenv("SPATIAL_BENCH_MAX_RADIUS", "20.0"))
        limit = int(os.getenv("SPATIAL_BENCH_LIMIT", "100"))
        warmup = int(os.getenv("SPATIAL_BENCH_WARMUP", "3"))
        seed = os.getenv("SPATIAL_BENCH_SEED")
        seed = int(seed) if seed is not None else None

        if not Images.objects.using("fram").exists():
            pytest.skip("No images available in fram database")

        try:
            stats = run_benchmark(
                iterations=iterations,
                min_radius=min_radius,
                max_radius=max_radius,
                limit=limit,
                warmup=warmup,
                seed=seed,
            )
        except db_utils.ProgrammingError as exc:
            if "q3c_radial_query" in str(exc):
                pytest.skip("q3c extension not available")
            raise

        if stats is None:
            pytest.skip("No spatial queries executed")

        print(
            "\nSpatial query benchmark "
            f"(mean {stats['mean_ms']:.2f}ms, p95 {stats['p95_ms']:.2f}ms, "
            f"mean results {stats['mean_count']:.2f})"
        )
        assert stats["iterations"] == iterations
