"""
Custom metrics collection for Locust load testing

Tracks cache hits/misses, endpoint P95 times, and other custom metrics
"""
from locust import events
from collections import defaultdict
import time


class PerformanceMetrics:
    """
    Collect custom performance metrics during load testing
    """

    def __init__(self):
        self.cache_hits = 0
        self.cache_misses = 0
        self.endpoint_times = defaultdict(list)
        self.query_counts = defaultdict(int)
        self.slow_requests = []  # Track very slow requests
        self.error_counts = defaultdict(int)

    def record_cache_hit(self):
        """Record a cache hit"""
        self.cache_hits += 1

    def record_cache_miss(self):
        """Record a cache miss"""
        self.cache_misses += 1

    def record_endpoint_time(self, endpoint, duration_ms):
        """
        Record response time for an endpoint

        Args:
            endpoint: Endpoint name
            duration_ms: Response time in milliseconds
        """
        self.endpoint_times[endpoint].append(duration_ms)

        # Track very slow requests (>10s)
        if duration_ms > 10000:
            self.slow_requests.append({
                'endpoint': endpoint,
                'duration': duration_ms,
                'timestamp': time.time()
            })

    def record_query_count(self, endpoint, count):
        """
        Record database query count for an endpoint

        Args:
            endpoint: Endpoint name
            count: Number of queries
        """
        self.query_counts[endpoint] = count

    def record_error(self, endpoint, error_type='unknown'):
        """
        Record an error

        Args:
            endpoint: Endpoint name
            error_type: Type of error
        """
        key = f"{endpoint}:{error_type}"
        self.error_counts[key] += 1

    def get_cache_hit_rate(self):
        """
        Calculate cache hit rate

        Returns:
            Cache hit rate as percentage (0-100)
        """
        total = self.cache_hits + self.cache_misses
        return (self.cache_hits / total * 100) if total > 0 else 0

    def get_p95_times(self):
        """
        Get 95th percentile response times per endpoint

        Returns:
            Dict of endpoint -> P95 time in seconds
        """
        results = {}
        for endpoint, times in self.endpoint_times.items():
            if times:
                sorted_times = sorted(times)
                p95_idx = int(len(sorted_times) * 0.95)
                results[endpoint] = sorted_times[p95_idx] / 1000.0  # Convert to seconds
        return results

    def get_p99_times(self):
        """Get 99th percentile response times"""
        results = {}
        for endpoint, times in self.endpoint_times.items():
            if times:
                sorted_times = sorted(times)
                p99_idx = int(len(sorted_times) * 0.99)
                results[endpoint] = sorted_times[p99_idx] / 1000.0
        return results

    def get_avg_times(self):
        """Get average response times per endpoint"""
        results = {}
        for endpoint, times in self.endpoint_times.items():
            if times:
                results[endpoint] = sum(times) / len(times) / 1000.0
        return results

    def get_slow_requests(self, threshold_ms=10000):
        """
        Get list of slow requests above threshold

        Args:
            threshold_ms: Threshold in milliseconds

        Returns:
            List of slow requests
        """
        return [r for r in self.slow_requests if r['duration'] > threshold_ms]

    def get_summary(self):
        """
        Get summary of all metrics

        Returns:
            Dict with metric summary
        """
        return {
            'cache': {
                'hits': self.cache_hits,
                'misses': self.cache_misses,
                'hit_rate': self.get_cache_hit_rate()
            },
            'response_times': {
                'p95': self.get_p95_times(),
                'p99': self.get_p99_times(),
                'avg': self.get_avg_times()
            },
            'slow_requests': len(self.slow_requests),
            'errors': dict(self.error_counts),
            'query_counts': dict(self.query_counts)
        }

    def print_summary(self):
        """Print formatted summary to console"""
        print("\n" + "="*60)
        print("CUSTOM PERFORMANCE METRICS")
        print("="*60)

        # Cache metrics
        if self.cache_hits or self.cache_misses:
            print(f"\n📦 Cache Metrics:")
            print(f"   Hit rate: {self.get_cache_hit_rate():.2f}%")
            print(f"   Hits: {self.cache_hits}")
            print(f"   Misses: {self.cache_misses}")

        # P95 response times
        p95_times = self.get_p95_times()
        if p95_times:
            print(f"\n⏱️  P95 Response Times:")
            sorted_times = sorted(p95_times.items(), key=lambda x: x[1], reverse=True)[:15]
            for endpoint, time_s in sorted_times:
                print(f"   {endpoint:40} {time_s:>7.3f}s")

        # Slow requests
        slow = self.get_slow_requests()
        if slow:
            print(f"\n🐌 Slow Requests (>10s): {len(slow)}")
            for req in slow[-5:]:  # Show last 5
                print(f"   {req['endpoint']:40} {req['duration']/1000:.1f}s")

        # Errors
        if self.error_counts:
            print(f"\n❌ Errors:")
            sorted_errors = sorted(self.error_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            for error_key, count in sorted_errors:
                print(f"   {error_key:40} {count:>5} times")

        print("="*60)


# Global metrics instance
metrics = PerformanceMetrics()


# Hook into Locust events
@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, context, **kwargs):
    """
    Hook into Locust request events
    Called for every request
    """
    # Record endpoint response time
    metrics.record_endpoint_time(name, response_time)

    # Record errors
    if exception:
        error_type = type(exception).__name__
        metrics.record_error(name, error_type)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """
    Print metrics when test stops
    """
    metrics.print_summary()


# Export global metrics instance
__all__ = ['metrics', 'PerformanceMetrics']
