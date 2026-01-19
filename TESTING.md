# Performance Testing Guide

This guide covers the comprehensive performance testing suite for FRAM Archive.

## Table of Contents

1. [Setup](#setup)
2. [Pytest Performance Tests](#pytest-performance-tests)
3. [Locust Load Tests](#locust-load-tests)
4. [Baseline Recording](#baseline-recording)
5. [CI/CD Integration](#cicd-integration)
6. [Troubleshooting](#troubleshooting)

---

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- pytest, pytest-django - Unit performance tests
- locust - Load testing
- All existing dependencies

### 2. Configure Credentials

Copy the template and set your credentials:

```bash
cp config/.env.test .env.test
```

Edit `.env.test` and set:
```bash
TEST_USERNAME=your_test_username
TEST_PASSWORD=your_test_password
```

**Security:** Never commit `.env.test` with real credentials! It's in `.gitignore`.

### 3. Verify Setup

```bash
# Test credentials
python locust_tests/config/credentials.py

# List available environments
python locust_tests/config/environments.py
```

---

## Pytest Performance Tests

Unit-level performance tests that validate response times, query counts, and caching.

### Quick Start

```bash
# Run all performance tests
pytest tests/performance/ -v

# Run specific test file
pytest tests/performance/test_cache_effectiveness.py -v

# Run with markers
pytest tests/performance/ -v -m cache
pytest tests/performance/ -v -m "not slow"
```

### Test Categories

#### 1. Cache Effectiveness Tests

**Validates your two performance fixes!**

```bash
pytest tests/performance/test_cache_effectiveness.py -v
```

Tests:
- ✅ Calibration lookup memoization (>50x speedup)
- ✅ Photometry N+1 query fix (1 query instead of 10+)
- ✅ db_query memoization
- ✅ Cache hit rates

**Expected Results:**
- Calibration 2nd call: <10ms
- Photometry: Single `.values_list()` query
- Cache hit rate: >90%

#### 2. Endpoint Performance Tests

```bash
pytest tests/performance/test_endpoint_performance.py -v
```

Validates response time thresholds:
- Fast endpoints (<500ms): index, nights, cached previews
- Medium endpoints (0.5-2s): search, image list
- Expensive endpoints (1-5s): analysis, photometry
- Very expensive (5-20s): WCS, zero point, filters

Synthetic preview benchmark (no FITS I/O, raw path only):
```bash
# Benchmark full/view/preview sizes with synthetic 4096x4096 data
PREVIEW_BENCH_ITERS=100 pytest tests/performance/test_endpoint_performance.py -k synthetic -m slow -s
```
This monkeypatches FITS loading and overscan cropping, reuses a fixed array, and measures the pure preview/rendering cost for `/full`, `/view` (800px), and `/preview` (128px).

#### 3. Query Efficiency Tests

```bash
pytest tests/performance/test_query_efficiency.py -v
```

Validates:
- Image list: ≤5 queries
- Calibration lookups: 0 queries when cached
- Photometry: single query
- No N+1 patterns

### Test Markers

```bash
# Only cache-related tests
pytest tests/performance/ -m cache

# Only query tests
pytest tests/performance/ -m query

# Exclude slow tests (>10s)
pytest tests/performance/ -m "not slow"

# Only slow tests
pytest tests/performance/ -m slow
```

### Generate Reports

```bash
# HTML report
pytest tests/performance/ --html=performance_report.html --self-contained-html

# Show slowest tests
pytest tests/performance/ --durations=20

# Coverage report
pytest tests/performance/ --cov=archive --cov-report=html
```

---

## Locust Load Tests

Realistic load testing with multiple user scenarios.

### Quick Start

```bash
# Local test (10 users, 5 minutes)
locust --config=locust.conf

# Access web UI: http://localhost:8089
```

**Smart Image ID Selection:**
When testing against localhost, Locust automatically uses Django ORM to fetch real image IDs from the database instead of random IDs. This ensures tests use valid data and provides more realistic load patterns. For remote servers, it falls back to generating random IDs.

Detection works by checking:
1. `LOCUST_HOST` environment variable (highest priority)
2. Configured environment from `LOCUST_ENV` (local, staging, production, stress)
3. Defaults to 'local' environment if neither is set

Examples:
- `locust --config=locust.conf` → Uses local environment (localhost) → **Django ORM**
- `LOCUST_ENV=production locust` → Uses production URL → **Random IDs**
- `LOCUST_HOST=http://localhost:8000 locust` → Explicit localhost → **Django ORM**

### User Scenarios

The load test simulates four types of users:

1. **Browser User (60%)** - Casual browsing
   - Viewing homepage, image lists
   - Previewing images
   - Downloading small files

2. **Researcher User (30%)** - Scientific analysis
   - Searching by coordinates
   - Requesting cutouts
   - Downloading photometry

3. **Power User (10%)** - Heavy analysis
   - Full resolution downloads
   - Running WCS verification
   - Photometric calibration

4. **Cache Tester (5%)** - Cache monitoring
   - Tests cache effectiveness
   - Validates speedup

### Environment Configurations

```bash
# Local (10 users, quick test)
LOCUST_ENV=local locust

# Staging (50 users)
LOCUST_ENV=staging locust -u 50 -r 5 -t 15m

# Production (100 users) - Use with caution!
LOCUST_ENV=production locust -u 100 -r 10 -t 30m

# Stress test (200 users)
LOCUST_ENV=stress locust -u 200 -r 20 -t 1h
```

### Headless Mode (No Web UI)

```bash
# Run without web interface
locust --headless -u 50 -r 5 -t 10m

# Save results
locust --headless -u 100 -r 10 -t 10m \
  --html=reports/report.html \
  --csv=reports/stats
```

### Custom Scenarios

Run specific user scenarios:

```bash
# Only browser users
locust -f locust_tests/scenarios/browser_user.py -u 20 -t 5m

# Only cache testing
locust -f locust_tests/scenarios/cache_tester.py -u 10 -t 5m

# Only power users (expensive operations)
locust -f locust_tests/scenarios/power_user.py -u 5 -t 10m
```

### Advanced Options

```bash
# Gradual ramp-up
locust --step-load --step-users 20 --step-time 2m -u 100 -t 20m

# Stop on failure threshold
locust --stop-timeout 60 --exit-code-on-error 1

# Set host explicitly
locust --host=http://localhost:18000 -u 50 -t 10m
```

---

## Baseline Recording

Track performance over time and detect regressions.

### Record Baseline

After running a load test:

```bash
# Record current performance as baseline
python locust_tests/utils/baseline_recorder.py record "After calibration fix"
```

This saves:
- P95 response times for all endpoints
- Git commit hash
- Timestamp
- Description

### Compare to Baseline

```bash
# Compare current run to latest baseline
python locust_tests/utils/baseline_recorder.py compare

# Compare to specific baseline
python locust_tests/utils/baseline_recorder.py compare baseline_20240115_143022_a1b2c3d4
```

**Regression Detection:**
- Alerts if any endpoint is >20% slower
- Shows improvements (>10% faster)
- Exits with code 1 on regression (CI-friendly)

### List Baselines

```bash
python locust_tests/utils/baseline_recorder.py list
```

### CI/CD Integration

```bash
# Run test, record baseline, compare
locust --headless -u 100 -r 10 -t 10m
python locust_tests/utils/baseline_recorder.py record "CI build $BUILD_NUMBER"
python locust_tests/utils/baseline_recorder.py compare || echo "Performance regression detected!"
```

---

## Common Workflows

### 1. Validate Performance Fixes

After implementing a performance improvement:

```bash
# Run cache effectiveness tests
pytest tests/performance/test_cache_effectiveness.py -v

# Run query efficiency tests
pytest tests/performance/test_query_efficiency.py -v

# Run load test
locust --headless -u 50 -r 5 -t 5m

# Record new baseline
python locust_tests/utils/baseline_recorder.py record "After [fix description]"
```

### 2. Pre-Deployment Testing

Before deploying:

```bash
# Run all pytest tests
pytest tests/performance/ -v -m "not slow"

# Run load test against staging
LOCUST_ENV=staging locust --headless -u 50 -r 5 -t 15m

# Compare to baseline
python locust_tests/utils/baseline_recorder.py compare
```

### 3. Find Performance Bottlenecks

```bash
# Run with profiling (creates .prof files in prof/ directory)
pytest tests/performance/ -v --profile

# View profiling results - look for combined.prof and individual test .prof files
ls -lh prof/

# Run expensive endpoint tests
pytest tests/performance/test_endpoint_performance.py::TestVeryExpensiveEndpoints -v

# Load test with power users only
locust -f locust_tests/scenarios/power_user.py -u 10 -t 10m
```

**Note:** Profiling requires `pytest-profiling` (included in requirements.txt). Profile files are saved to `prof/` directory and show function call times to identify bottlenecks.

### 4. Cache Effectiveness Testing

```bash
# Test cache improvements
pytest tests/performance/test_cache_effectiveness.py -v

# Load test with cache monitoring
locust -f locust_tests/scenarios/cache_tester.py -u 10 -t 5m
```

---

## Interpreting Results

### Pytest Results

**Success indicators:**
- All tests pass
- Cache hit rate >90%
- Query counts within limits
- Response times under thresholds

**Warning signs:**
- Cache hit rate <80%
- Increasing query counts
- Response times near thresholds

### Locust Results

**Key metrics:**
- **Failure rate:** Should be <1%
- **P95 response time:** Within endpoint thresholds
- **Requests/sec:** Measure of throughput
- **Cache hit rate:** >80% under load

**Access web UI:** http://localhost:8089
- Charts tab: Visual response time distribution
- Failures tab: See error details
- Download data: CSV export for analysis

---

## Troubleshooting

### Tests Fail with Authentication Error

```bash
# Check credentials are set
cat .env.test | grep TEST_USERNAME

# Test credentials
python locust_tests/config/credentials.py

# Ensure .env.test is in working directory
ls -la .env.test
```

### "No images in database"

Tests require at least some images in the database:

```bash
# Check database
python manage.py shell
>>> from archive.models import Images
>>> Images.objects.count()
```

If count is 0, the database is empty. Tests will skip automatically.

### Cache Tests Failing

Cache must be enabled and working:

```bash
# Check cache settings
python manage.py shell
>>> from django.core.cache import cache
>>> cache.set('test', 'value')
>>> cache.get('test')  # Should return 'value'
```

### Locust Connection Errors

```bash
# Ensure server is running
curl http://localhost:18000/

# Check host configuration
python locust_tests/config/environments.py

# Test with explicit host
locust --host=http://localhost:18000
```

### Slow Tests Timeout

Some tests are marked as slow (>10s):

```bash
# Increase timeout
pytest tests/performance/ --timeout=60

# Skip slow tests
pytest tests/performance/ -m "not slow"
```

---

## Performance Test Checklist

Before committing changes:

- [ ] Run cache effectiveness tests
- [ ] Run query efficiency tests
- [ ] Run endpoint performance tests (skip slow if needed)
- [ ] Verify no regressions in baseline comparison

Before deploying:

- [ ] Run full pytest suite
- [ ] Run load test (staging environment)
- [ ] Compare to baseline
- [ ] Record new baseline if improvements made
- [ ] Review Locust reports for errors

---

## Additional Resources

- **Plan:** `/Users/karpov/.claude/plans/atomic-jumping-yao.md` - Full implementation plan
- **Bottlenecks:** `PERFORMANCE_BOTTLENECKS.md` - Identified performance issues
- **Architecture:** `CLAUDE.md` - System architecture overview

## Support

For issues or questions:
1. Check this guide's troubleshooting section
2. Review test output for specific error messages
3. Check `.env.test` configuration
4. Verify test database has data
