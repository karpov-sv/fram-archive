# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FRAM Archive is a Django web portal for accessing and analyzing data from FRAM telescopes. The application provides image browsing, cutout generation, and photometry analysis for astronomical observations.

## Development Commands

### Running the Development Server
```bash
python manage.py runserver
```

### Database Operations
The project uses two databases:
- `default`: SQLite for Django models (auth, sessions, etc.)
- `fram`: PostgreSQL for observational data (read-only)

```bash
# Create/update default database migrations
python manage.py makemigrations

# Apply migrations to default database
python manage.py migrate

# Note: Do not migrate the 'fram' database - it's managed externally
```

### Custom Management Commands
```bash
# Set default permissions
python manage.py defaultpermissions
```

### Installing Dependencies
```bash
pip install -r requirements.txt
```

## Architecture Overview

### Multi-Database Architecture
The project uses a custom database router (`archive/routers.py`) to separate Django models from observational data:
- Models with `app_label='fram'` route to the PostgreSQL `fram` database
- All other models use the default SQLite database
- The `fram` database contains unmanaged models (`managed = False`) for read-only access

### Core Application Structure
The `archive` app is organized into specialized view modules:
- `views.py`: Main index, search functionality, and form handling
- `views_images.py`: Image listing, detail views, previews, downloads, cutouts, and analysis
- `views_photometry.py`: Photometry lightcurve generation and export in multiple formats

### Models (`archive/models.py`)
All models are unmanaged and map to existing PostgreSQL tables:
- `Images`: Main observational images with astronomical metadata
- `Calibrations`: Calibration frames (bias, dark, flat)
- `Photometry`: Time-series photometry data

### External Dependencies
The project relies on an external `fram` Python module (not in this repo):
- Located via symlinks: `data -> ../fram/data` and `photometry -> ../fram/photometry`
- Imported modules: `fram.resolve`, `fram.calibrate`, `fram.survey`, `fram.utils`, `fram.fram`
- Contains telescope-specific processing logic

### Query Optimization
- `db_query()` function in `utils.py` provides memoized database queries with 600s cache timeout
- Used for expensive queries to PostgreSQL fram database
- Cache key generation supports custom `make_key` parameter for better control

### Image Processing Pipeline
Images can be downloaded in two forms:
1. Raw FITS files from original observations
2. Processed files with calibration applied

Calibration selection (`find_calibration_image()` in `views_images.py`):
- Finds appropriate bias, dark, and flat frames based on exposure, binning, filter, CCD
- Searches for closest calibration by night (before image date, or after if none found)

### Spatial Queries
- Uses PostgreSQL q3c extension for spatial indexing
- Functions like `q3c_radial_query()` for cone searches
- HTM (Hierarchical Triangular Mesh) library for spatial operations

### Frontend Technologies
- Bootstrap 5 via crispy-bootstrap5
- Django EL Pagination for image list pagination
- Custom JavaScript for image overlays and help popovers
- Dark mode support via `dark.css`

## Configuration

### Environment Variables (.env)
Required configuration via python-decouple:
- `SECRET_KEY`: Django secret key
- `DEBUG`: Debug mode (default: False)
- `ALLOWED_HOSTS`: Comma-separated list of allowed hosts
- `CSRF_TRUSTED_ORIGINS`: Comma-separated list of trusted origins

### PostgreSQL Database Setup
The `fram` database connection in `settings.py` needs to be configured with appropriate credentials for your PostgreSQL instance.

### Performance Profiling
The project includes django-cprofile-middleware for performance analysis. Access profiling data via query parameters in development mode.

## URL Structure

- `/` - Site overview and statistics
- `/search/` - Image search form
- `/search/cutouts/` - Cutout search interface
- `/search/photometry/` - Photometry search interface
- `/images/` - Image listing with pagination
- `/images/<id>/` - Detailed image view
- `/images/<id>/preview` - Small preview (128px)
- `/images/<id>/view` - Medium view (800px)
- `/images/<id>/full` - Full resolution view
- `/images/<id>/download` - Download raw FITS
- `/images/<id>/download/processed` - Download processed FITS
- `/images/<id>/cutout` - Generate cutout around coordinates
- `/images/<id>/bg|fwhm|wcs|filters|zero` - Analysis endpoints
- `/photometry/lc` - Lightcurve as JPEG
- `/photometry/json` - Lightcurve data as JSON
- `/photometry/text` - Lightcurve as text
- `/photometry/mjd` - Lightcurve with MJD timestamps
- `/nights/` - Browse images by observation night

## Testing Infrastructure

The project has a comprehensive performance testing suite covering unit tests and load testing. See `TESTING.md` for detailed documentation.

### Test Configuration

**Test Credentials:** All tests use credentials from `.env.test` (not `.env`):
```bash
# .env.test contains:
TEST_USERNAME=your_username
TEST_PASSWORD=your_password
```

Both pytest and Locust tests load credentials from this file using `Config(RepositoryEnv('.env.test'))` from python-decouple.

**Database Access:** Tests use both databases:
- `default`: SQLite for Django auth/sessions
- `fram`: PostgreSQL for observational data (read-only)
- All test classes are marked with `@pytest.mark.django_db(databases=['fram', 'default'])`

### Pytest Performance Tests

Located in `tests/performance/`, these validate response times, query counts, and caching effectiveness.

**Quick Start:**
```bash
# Run all performance tests (excluding slow tests >10s)
pytest tests/performance/ -v -m "not slow"

# Run specific test categories
pytest tests/performance/test_cache_effectiveness.py -v  # Cache/memoization tests
pytest tests/performance/test_query_efficiency.py -v     # Database query tests
pytest tests/performance/test_endpoint_performance.py -v # Response time tests
```

**Test Categories:**
- **Cache Effectiveness** (`test_cache_effectiveness.py`): Validates memoization of `find_calibration_image()`, photometry query optimization, and `db_query()` caching
- **Query Efficiency** (`test_query_efficiency.py`): Validates query counts, checks for N+1 patterns, tests spatial queries
- **Endpoint Performance** (`test_endpoint_performance.py`): Validates response time thresholds for fast (<500ms), medium (0.5-2s), and expensive (1-5s) endpoints

**Current Status:** 45/47 tests passing (96%)
- The two failures are genuine, and are left failing on purpose. Both are one expensive query and nothing else: `/nights/` aggregates the whole `images` table to count every night of every site, which takes seconds on a cold cache and is then held for an hour by `cache_page`, and the cutouts list pays a q3c `COUNT(*)` of the cone before it can lay out its pages. Neither is fixable in the application - they want a summary table and a better spatial index respectively.
- Query counts of the views are asserted with `database='fram'`, so that the session and user rows the authenticated test client reads from the default database do not count against them.
- `assert_query_count` yields a record which holds `count` and `queries` once the block is over, for a test comparing two of them rather than pinning a number.

**Key Fixtures** (in `tests/conftest.py`):
- `client`: Authenticated Django test client (auto-loads credentials from .env.test)
- `test_image`: Returns a valid image from the database for testing
- `test_coordinates`: Returns test coordinates for spatial queries (M31 region)
- `assert_query_count(n, tolerance)`: Context manager for asserting query counts
- `assert_time_under(seconds, description)`: Context manager for timing assertions

### Locust Load Testing

Located in `locust_tests/`, provides realistic multi-user load testing.

**Quick Start:**
```bash
# Local development test (10 users, web UI)
locust --config=locust.conf

# Headless mode with specific parameters
locust --headless -u 50 -r 5 -t 10m --html=report.html

# Custom environment
LOCUST_ENV=staging locust -u 50 -r 5 -t 15m
```

**Smart Image ID Selection:**
When testing against localhost, Locust automatically uses Django ORM to fetch real image IDs from the database. For remote servers, it generates random IDs. Detection checks both `LOCUST_HOST` environment variable (highest priority) and the configured environment from `LOCUST_ENV` (local/staging/production/stress). This ensures realistic testing with valid data locally while maintaining portability for remote testing.

**User Scenarios** (in `locust_tests/scenarios/`):
- `browser_user.py`: Casual browsing (60% of users) - homepage, lists, previews
- `researcher_user.py`: Scientific analysis (30%) - searches, cutouts, photometry
- `power_user.py`: Heavy operations (10%) - full downloads, WCS, calibration
- `cache_tester.py`: Cache monitoring (5%) - validates cache effectiveness

**Environments** (in `locust_tests/config/environments.py`):
- `local`: http://localhost:18000 - 10 users, spawn rate 2
- `staging`: staging.fram.example.com - 50 users, spawn rate 5
- `production`: https://pc048b.fzu.cz/archive/ - 100 users, spawn rate 10
- `stress`: localhost - 200 users, spawn rate 20 (stress testing)

**Baseline Recording:**
```bash
# Record performance baseline after changes
python locust_tests/utils/baseline_recorder.py record "Description of changes"

# Compare current performance to baseline (CI-friendly, exits with code 1 on regression)
python locust_tests/utils/baseline_recorder.py compare

# List all recorded baselines
python locust_tests/utils/baseline_recorder.py list
```

**Configuration Files:**
- `locust.conf`: Default Locust configuration
- `locust_tests/config/credentials.py`: Credential management (loads from .env.test)
- `locust_tests/config/environments.py`: Environment definitions
- `locust_tests/utils/baseline_recorder.py`: Performance baseline tracking

### Running Tests in CI/CD

```bash
# Install test dependencies
pip install -r requirements.txt

# Run pytest performance tests
pytest tests/performance/ -v -m "not slow" --html=pytest_report.html

# Run Locust load test
locust --headless -u 100 -r 10 -t 10m --html=locust_report.html

# Record baseline and check for regressions
python locust_tests/utils/baseline_recorder.py record "CI build $BUILD_NUMBER"
python locust_tests/utils/baseline_recorder.py compare || echo "⚠️ Performance regression detected"
```

### Test Markers

Pytest tests use markers for selective execution:
- `@pytest.mark.performance`: All performance tests
- `@pytest.mark.slow`: Tests taking >10 seconds
- `@pytest.mark.cache`: Cache-related tests
- `@pytest.mark.query`: Database query tests

Use `-m` flag to filter: `pytest -m "cache and not slow"`

## Important Patterns

### Permission Handling
The logging configuration filters out `PermissionDenied` exceptions (see `utils.IgnorePermissionDeniedFilter`) to reduce noise in logs. Permission-restricted views use `@permission_required` decorator.

### Form Handling with Astronomical Coordinates
The `ImagesSearchForm` accepts coordinates or object names via the `coords` field. Name resolution is handled by `fram.resolve.resolve()` which returns name, RA, and Dec.

### Search Radius Units
Search forms accept radius with selectable units (degrees, arcmin, arcsec) that are normalized to degrees before database queries.

### Context Processors
`archive.context_processors.expose_settings` makes settings available in templates.

### Template Customization
Custom crispy forms templates in `archive/templates/` provide specialized rendering for form fields and pagination.
