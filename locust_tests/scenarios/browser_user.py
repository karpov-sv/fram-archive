"""
Browser User Scenario - 60% of traffic

Simulates casual users browsing the archive:
- Viewing homepage and night lists
- Browsing image lists with filters
- Viewing image previews and details
- Occasional downloads

Wait time: 3-10 seconds (realistic browsing behavior)
"""
from locust import HttpUser, task, between
import random

from locust_tests.config.credentials import Credentials
from locust_tests.utils.data_helpers import (
    get_random_image_ids,
    SearchParameterHelper
)


class BrowserUser(HttpUser):
    """Simulates casual users browsing the archive"""

    wait_time = between(3, 10)  # Realistic think time between requests
    weight = 60  # 60% of total users

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

        # Pre-generate list of image IDs to test
        self.image_ids = get_random_image_ids(100, id_range=(1, 10000))

    @task(10)
    def view_index(self):
        """Visit homepage to see site statistics"""
        with self.client.get("/", catch_response=True, name="Index") as response:
            if response.status_code != 200:
                response.failure(f"Got status {response.status_code}")

    @task(5)
    def browse_nights(self):
        """Browse night list"""
        params = {}

        # Sometimes filter by site
        if random.random() < 0.3:
            params['site'] = SearchParameterHelper.get_random_site()

        with self.client.get(
            "/nights/",
            params=params,
            catch_response=True,
            name="Nights"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Got status {response.status_code}")

    @task(15)
    def view_image_list(self):
        """Browse image list with various filters"""
        params = SearchParameterHelper.get_random_search_params()

        with self.client.get(
            "/images/",
            params=params,
            catch_response=True,
            name="Image List"
        ) as response:
            if response.status_code not in [200, 302]:
                response.failure(f"Got status {response.status_code}")

    @task(30)
    def view_image_preview(self):
        """View medium-sized image preview (most common action)"""
        img_id = random.choice(self.image_ids)

        with self.client.get(
            f"/images/{img_id}/view",
            catch_response=True,
            name="Image View"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Image {img_id} preview failed: {response.status_code}")

    @task(10)
    def view_image_details(self):
        """View detailed image information page"""
        img_id = random.choice(self.image_ids)

        with self.client.get(
            f"/images/{img_id}/",
            catch_response=True,
            name="Image Details"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Image {img_id} details failed: {response.status_code}")

    @task(5)
    def download_small_preview(self):
        """Download small preview thumbnail"""
        img_id = random.choice(self.image_ids)

        with self.client.get(
            f"/images/{img_id}/preview",
            catch_response=True,
            name="Preview Download"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Preview download failed: {response.status_code}")

    @task(3)
    def view_full_image(self):
        """View full resolution image (less common)"""
        img_id = random.choice(self.image_ids)

        with self.client.get(
            f"/images/{img_id}/full",
            catch_response=True,
            name="Full Image"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Full image failed: {response.status_code}")
            elif response.elapsed.total_seconds() > 10:
                response.failure(f"Full image took {response.elapsed.total_seconds():.1f}s (>10s)")

    @task(2)
    def browse_with_spatial_filter(self):
        """Browse images with spatial filtering (less common)"""
        from locust_tests.utils.data_helpers import get_random_target, SearchRadiusHelper

        target = get_random_target()
        sr_value, sr_units = SearchRadiusHelper.get_search_radius('normal')

        params = {
            'ra': target['ra'],
            'dec': target['dec'],
            'sr': sr_value / 60 if sr_units == 'arcmin' else sr_value  # Convert to degrees
        }

        # Add some additional filters
        if random.random() < 0.5:
            params['filter'] = SearchParameterHelper.get_random_filter()

        with self.client.get(
            "/images/",
            params=params,
            catch_response=True,
            name="Spatial Search"
        ) as response:
            if response.status_code not in [200, 302]:
                response.failure(f"Spatial search failed: {response.status_code}")
