#!/usr/bin/env python3
"""
Benchmark q3c radial query performance for random sky regions.
"""
import argparse
import os
import random
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archive.settings")

import django  # noqa: E402

django.setup()

from archive.models import Images  # noqa: E402


def run_query(ra, dec, sr, limit):
    images = Images.objects.using("fram").all()
    images = images.extra(
        where=["q3c_radial_query(ra, dec, %s, %s, %s)"],
        params=(ra, dec, sr),
    )

    if limit > 0:
        results = list(images.values_list("id", flat=True)[:limit])
        return len(results)

    return images.count()


def percentile(values, percent):
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (percent / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    d0 = ordered[f] * (c - k)
    d1 = ordered[c] * (k - f)
    return d0 + d1


def compute_stats(durations, counts):
    mean_ms = (sum(durations) / len(durations)) * 1000.0
    p50_ms = percentile(durations, 50.0) * 1000.0
    p95_ms = percentile(durations, 95.0) * 1000.0
    min_ms = min(durations) * 1000.0
    max_ms = max(durations) * 1000.0
    mean_count = sum(counts) / len(counts) if counts else 0.0

    return {
        "mean_ms": mean_ms,
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "min_ms": min_ms,
        "max_ms": max_ms,
        "mean_count": mean_count,
    }


def run_benchmark(iterations, min_radius, max_radius, limit, warmup, seed=None):
    if seed is not None:
        random.seed(seed)

    for _ in range(warmup):
        ra = random.uniform(0.0, 360.0)
        dec = random.uniform(-90.0, 90.0)
        sr = random.uniform(min_radius, max_radius)
        run_query(ra, dec, sr, limit)

    durations = []
    counts = []

    for _ in range(iterations):
        ra = random.uniform(0.0, 360.0)
        dec = random.uniform(-90.0, 90.0)
        sr = random.uniform(min_radius, max_radius)

        start = time.perf_counter()
        count = run_query(ra, dec, sr, limit)
        durations.append(time.perf_counter() - start)
        counts.append(count)

    if not durations:
        return None

    stats = compute_stats(durations, counts)
    stats.update(
        {
            "iterations": len(durations),
            "warmup": warmup,
            "min_radius": min_radius,
            "max_radius": max_radius,
            "limit": limit,
            "durations": durations,
            "counts": counts,
        }
    )
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark spatial image queries using q3c_radial_query."
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="Number of queries to run.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible sampling.",
    )
    parser.add_argument(
        "--min-radius",
        type=float,
        default=0.1,
        help="Minimum search radius in degrees.",
    )
    parser.add_argument(
        "--max-radius",
        type=float,
        default=20.0,
        help="Maximum search radius in degrees.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of IDs to fetch per query (0 for count only).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=3,
        help="Number of warm-up queries (not timed).",
    )
    args = parser.parse_args()

    if args.min_radius <= 0 or args.max_radius <= 0:
        print("Radius bounds must be positive.")
        return 1

    if args.max_radius < args.min_radius:
        print("max-radius must be >= min-radius.")
        return 1

    stats = run_benchmark(
        iterations=args.iterations,
        min_radius=args.min_radius,
        max_radius=args.max_radius,
        limit=args.limit,
        warmup=args.warmup,
        seed=args.seed,
    )
    if stats is None:
        print("No queries executed.")
        return 1

    mode = "count" if args.limit == 0 else f"fetch {args.limit}"
    print("Spatial query benchmark")
    print(f"iterations: {stats['iterations']} (warmup: {stats['warmup']})")
    print(f"radius range: {stats['min_radius']}..{stats['max_radius']} deg")
    print(f"mode: {mode}")
    print(f"mean time: {stats['mean_ms']:.2f} ms")
    print(f"p50 time: {stats['p50_ms']:.2f} ms")
    print(f"p95 time: {stats['p95_ms']:.2f} ms")
    print(f"min/max time: {stats['min_ms']:.2f} / {stats['max_ms']:.2f} ms")
    print(f"mean results: {stats['mean_count']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
