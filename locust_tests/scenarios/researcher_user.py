"""
Researcher User Scenario - 30% of traffic

Simulates researchers searching and analyzing data:
- Searching by coordinates and filters
- Requesting cutouts
- Downloading photometry data
- Generating light curves

Wait time: 5-15 seconds (thoughtful analysis)
"""
from locust import HttpUser, task, between
import random

from locust_tests.config.credentials import Credentials
from locust_tests.utils.data_helpers import (
    get_random_image_ids,
    get_random_target,
    SearchParameterHelper,
    SearchRadiusHelper
)


class ResearcherUser(HttpUser):
    """Simulates researchers searching and analyzing data"""

    wait_time = between(5, 15)  # Thoughtful analysis time
    weight = 30  # 30% of total users

    def on_start(self):
        """Called when user starts - perform login"""
        try:
            Credentials.login(self.client)
            self.logged_in = True
        except Exception as e:
            print(f"Login failed: {e}")
            self.logged_in = False
            self.environment.runner.quit()
            return

        # Pre-generate test data
        self.image_ids = get_random_image_ids(50, id_range=(1, 10000))
        # Researchers tend to focus on specific targets
        self.research_targets = [get_random_target() for _ in range(5)]

    @task(15)
    def search_by_filters(self):
        """Search images by various filters"""
        params = SearchParameterHelper.get_random_search_params()

        # Researchers more likely to use date ranges
        if 'night1' not in params and random.random() < 0.7:
            night1, night2 = SearchParameterHelper.get_random_night_range()
            params['night1'] = night1
            params['night2'] = night2

        with self.client.get(
            "/images/",
            params=params,
            catch_response=True,
            name="Filtered Search"
        ) as response:
            if response.status_code not in [200, 302]:
                response.failure(f"Search failed: {response.status_code}")

    @task(10)
    def search_by_coordinates(self):
        """Search by sky coordinates using search form"""
        target = random.choice(self.research_targets)
        sr_value, sr_units = SearchRadiusHelper.get_search_radius('normal')

        # Use POST to search form
        search_data = {
            'coords': f"{target['ra']} {target['dec']}",
            'sr_value': sr_value,
            'sr_units': sr_units,
        }

        # Sometimes add filters
        if random.random() < 0.5:
            search_data['filter'] = SearchParameterHelper.get_random_filter()

        with self.client.post(
            "/search/",
            data=search_data,
            catch_response=True,
            name="Coordinate Search"
        ) as response:
            if response.status_code not in [200, 302]:
                response.failure(f"Coordinate search failed: {response.status_code}")

    @task(8)
    def get_cutouts_list(self):
        """Get list of cutouts for a target"""
        target = random.choice(self.research_targets)
        sr = SearchRadiusHelper.get_cutout_radius()

        params = {
            'ra': target['ra'],
            'dec': target['dec'],
            'sr': sr
        }

        # Researchers often filter by band
        if random.random() < 0.7:
            params['filter'] = SearchParameterHelper.get_random_filter()

        with self.client.get(
            "/images/cutouts/",
            params=params,
            catch_response=True,
            name="Cutouts List"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Cutouts list failed: {response.status_code}")
            elif response.elapsed.total_seconds() > 3:
                response.failure(f"Cutouts list took {response.elapsed.total_seconds():.1f}s")

    @task(12)
    def view_cutout(self):
        """View individual cutout"""
        target = random.choice(self.research_targets)
        img_id = random.choice(self.image_ids)
        sr = SearchRadiusHelper.get_cutout_radius()

        params = {
            'ra': target['ra'],
            'dec': target['dec'],
            'sr': sr
        }

        with self.client.get(
            f"/images/{img_id}/cutout",
            params=params,
            catch_response=True,
            name="Cutout View"
        ) as response:
            # Cutout may fail if image doesn't overlap coordinates
            if response.status_code not in [200, 500]:
                response.failure(f"Cutout view unexpected status: {response.status_code}")
            elif response.status_code == 200 and response.elapsed.total_seconds() > 5:
                response.failure(f"Cutout took {response.elapsed.total_seconds():.1f}s")

    @task(10)
    def get_photometry_json(self):
        """Get photometry data as JSON"""
        target = random.choice(self.research_targets)
        sr = SearchRadiusHelper.get_photometry_radius()

        params = {
            'ra': target['ra'],
            'dec': target['dec'],
            'sr': sr,
        }

        # Often filter by band for photometry
        if random.random() < 0.8:
            params['filter'] = random.choice(['B', 'V', 'R', 'I'])

        with self.client.get(
            "/photometry/json",
            params=params,
            catch_response=True,
            name="Photometry JSON"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Photometry JSON failed: {response.status_code}")
            elif response.elapsed.total_seconds() > 3:
                response.failure(f"Photometry JSON took {response.elapsed.total_seconds():.1f}s")

    @task(5)
    def get_light_curve(self):
        """Get light curve plot"""
        target = random.choice(self.research_targets)
        sr = SearchRadiusHelper.get_photometry_radius()

        params = {
            'ra': target['ra'],
            'dec': target['dec'],
            'sr': sr,
            'name': target['name']
        }

        with self.client.get(
            "/photometry/lc",
            params=params,
            catch_response=True,
            name="Light Curve"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Light curve failed: {response.status_code}")
            elif response.elapsed.total_seconds() > 5:
                response.failure(f"Light curve took {response.elapsed.total_seconds():.1f}s")

    @task(7)
    def download_photometry_text(self):
        """Download photometry as text file"""
        target = random.choice(self.research_targets)
        sr = SearchRadiusHelper.get_photometry_radius()

        params = {
            'ra': target['ra'],
            'dec': target['dec'],
            'sr': sr,
        }

        with self.client.get(
            "/photometry/text",
            params=params,
            catch_response=True,
            name="Photometry Text"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Photometry text failed: {response.status_code}")

    @task(3)
    def download_cutout_fits(self):
        """Download cutout as FITS file"""
        target = random.choice(self.research_targets)
        img_id = random.choice(self.image_ids)
        sr = SearchRadiusHelper.get_cutout_radius()

        params = {
            'ra': target['ra'],
            'dec': target['dec'],
            'sr': sr,
            'mode': 'download'
        }

        with self.client.get(
            f"/images/{img_id}/cutout/download",
            params=params,
            catch_response=True,
            name="Cutout Download"
        ) as response:
            # May fail if no overlap
            if response.status_code not in [200, 500]:
                response.failure(f"Cutout download unexpected status: {response.status_code}")
