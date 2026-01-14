"""
Main Locust entry point for FRAM Archive load testing

This file imports all user scenarios and configures the load test.

Usage:
    # Local test
    locust --config=locust.conf

    # Specific environment
    LOCUST_ENV=staging locust -u 50 -r 5 -t 15m

    # Headless mode
    locust --headless -u 100 -r 10 -t 10m
"""
import os
from locust import events

from locust_tests.config.environments import get_environment
from locust_tests.scenarios.browser_user import BrowserUser
from locust_tests.scenarios.researcher_user import ResearcherUser
from locust_tests.scenarios.power_user import PowerUser
from locust_tests.scenarios.cache_tester import CacheTesterUser


# Get environment configuration
ENV_NAME = os.getenv('LOCUST_ENV', 'local')

try:
    env_config = get_environment(ENV_NAME)
except ValueError as e:
    print(f"Error: {e}")
    print("\nAvailable environments: local, staging, production, stress")
    exit(1)


# Export all user classes for Locust
__all__ = [
    'BrowserUser',      # 60% weight
    'ResearcherUser',   # 30% weight
    'PowerUser',        # 10% weight
    'CacheTesterUser',  # 5% weight (independent)
]


@events.init.add_listener
def on_locust_init(environment, **kwargs):
    """
    Initialize test environment
    Called when Locust starts
    """
    print("\n" + "="*60)
    print("FRAM Archive Load Testing")
    print("="*60)
    print(f"Environment: {env_config.name}")
    print(f"Target host: {env_config.host}")
    print(f"Target users: {env_config.users}")
    print(f"Spawn rate: {env_config.spawn_rate} users/second")
    print(f"Run time: {env_config.run_time}")
    print("\nUser Scenarios:")
    print(f"  - BrowserUser (60%): Casual browsing and viewing")
    print(f"  - ResearcherUser (30%): Searching and analyzing")
    print(f"  - PowerUser (10%): Heavy analysis and downloads")
    print(f"  - CacheTesterUser (5%): Cache effectiveness monitoring")
    print("="*60 + "\n")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """
    Called when load test starts
    """
    print(f"\n🚀 Starting load test against {env_config.host}")
    print(f"   Ramping up to {env_config.users} users...\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """
    Called when load test stops
    Print summary statistics
    """
    print("\n" + "="*60)
    print("Load Test Complete")
    print("="*60)

    stats = environment.stats

    print(f"\nTotal requests: {stats.total.num_requests}")
    print(f"Total failures: {stats.total.num_failures}")
    print(f"Failure rate: {stats.total.fail_ratio*100:.2f}%")
    print(f"Average response time: {stats.total.avg_response_time:.0f}ms")
    print(f"Max response time: {stats.total.max_response_time:.0f}ms")
    print(f"Requests/sec: {stats.total.total_rps:.2f}")

    # Print slowest endpoints
    print("\n📊 Slowest endpoints (P95):")
    sorted_stats = sorted(
        stats.entries.values(),
        key=lambda x: x.get_response_time_percentile(0.95),
        reverse=True
    )[:10]

    for stat in sorted_stats:
        p95 = stat.get_response_time_percentile(0.95)
        print(f"   {stat.name:40} {p95:>7.0f}ms")

    # Print most failed endpoints
    failed_stats = [s for s in stats.entries.values() if s.num_failures > 0]
    if failed_stats:
        print("\n❌ Failed endpoints:")
        sorted_failures = sorted(
            failed_stats,
            key=lambda x: x.num_failures,
            reverse=True
        )[:10]

        for stat in sorted_failures:
            fail_rate = (stat.num_failures / stat.num_requests * 100) if stat.num_requests > 0 else 0
            print(f"   {stat.name:40} {stat.num_failures:>5} failures ({fail_rate:.1f}%)")

    print("\n" + "="*60)
    print(f"📈 Detailed report: locust_tests/reports/locust_report.html")
    print("="*60 + "\n")


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    """
    Called for each request
    Can be used for custom metrics collection
    """
    # Add custom logic here if needed
    # For example, track specific slow requests
    if response_time > 10000:  # > 10 seconds
        print(f"⚠️  Slow request: {name} took {response_time/1000:.1f}s")
