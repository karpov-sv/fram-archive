"""
Power User Scenario - 10% of traffic

Simulates power users doing heavy analysis:
- Downloading full resolution images
- Running analysis endpoints (WCS, FWHM, photometric calibration)
- Processing raw data
- Intensive computational tasks

Wait time: 10-30 seconds (patient, waiting for analysis)
"""
from locust import HttpUser, task, between
import random

from locust_tests.config.credentials import Credentials
from locust_tests.utils.data_helpers import get_random_image_ids


class PowerUser(HttpUser):
    """Simulates power users doing heavy analysis"""

    wait_time = between(10, 30)  # Patient users waiting for analysis
    weight = 10  # 10% of total users

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

        # Pre-generate image IDs
        self.image_ids = get_random_image_ids(30, id_range=(1, 10000))

    @task(10)
    def download_full_image(self):
        """Download full processed image"""
        img_id = random.choice(self.image_ids)

        with self.client.get(
            f"/images/{img_id}/full",
            catch_response=True,
            name="Full Image Download"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Full image download failed: {response.status_code}")
            elif response.elapsed.total_seconds() > 10:
                response.failure(f"Full image took {response.elapsed.total_seconds():.1f}s (>10s)")

    @task(5)
    def download_raw_fits(self):
        """Download raw FITS file"""
        img_id = random.choice(self.image_ids)

        with self.client.get(
            f"/images/{img_id}/full",
            params={'raw': '1'},
            catch_response=True,
            name="Raw FITS Download"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Raw download failed: {response.status_code}")

    @task(3)
    def download_processed_fits(self):
        """Download processed FITS file"""
        img_id = random.choice(self.image_ids)

        with self.client.get(
            f"/images/{img_id}/download/processed",
            catch_response=True,
            name="Processed FITS"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Processed FITS failed: {response.status_code}")
            elif response.elapsed.total_seconds() > 5:
                response.failure(f"Processed FITS took {response.elapsed.total_seconds():.1f}s")

    @task(3)
    def analyze_fwhm(self):
        """Get FWHM analysis"""
        img_id = random.choice(self.image_ids)

        with self.client.get(
            f"/images/{img_id}/fwhm",
            catch_response=True,
            name="FWHM Analysis"
        ) as response:
            if response.status_code not in [200, 500]:
                response.failure(f"FWHM analysis failed: {response.status_code}")
            elif response.status_code == 200 and response.elapsed.total_seconds() > 8:
                response.failure(f"FWHM took {response.elapsed.total_seconds():.1f}s (>8s)")

    @task(3)
    def analyze_background(self):
        """Get background analysis"""
        img_id = random.choice(self.image_ids)

        with self.client.get(
            f"/images/{img_id}/bg",
            catch_response=True,
            name="Background Analysis"
        ) as response:
            if response.status_code not in [200, 500]:
                response.failure(f"Background analysis failed: {response.status_code}")
            elif response.status_code == 200 and response.elapsed.total_seconds() > 8:
                response.failure(f"Background took {response.elapsed.total_seconds():.1f}s")

    @task(2)
    def verify_wcs(self):
        """WCS verification (very expensive)"""
        img_id = random.choice(self.image_ids)

        with self.client.get(
            f"/images/{img_id}/wcs",
            catch_response=True,
            name="WCS Verification"
        ) as response:
            if response.status_code not in [200, 500]:
                response.failure(f"WCS verification failed: {response.status_code}")
            elif response.status_code == 200:
                elapsed = response.elapsed.total_seconds()
                if elapsed > 25:
                    response.failure(f"WCS took {elapsed:.1f}s (>25s)")
                elif elapsed > 20:
                    print(f"⚠️  WCS took {elapsed:.1f}s (warning threshold)")

    @task(2)
    def photometric_calibration(self):
        """Photometric zero point analysis (very expensive)"""
        img_id = random.choice(self.image_ids)

        with self.client.get(
            f"/images/{img_id}/zero",
            catch_response=True,
            name="Photometric Calibration"
        ) as response:
            if response.status_code not in [200, 500]:
                response.failure(f"Photometric calibration failed: {response.status_code}")
            elif response.status_code == 200:
                elapsed = response.elapsed.total_seconds()
                if elapsed > 25:
                    response.failure(f"Zero point took {elapsed:.1f}s (>25s)")
                elif elapsed > 20:
                    print(f"⚠️  Zero point took {elapsed:.1f}s (warning threshold)")

    @task(1)
    def filter_analysis(self):
        """Multi-filter color analysis (very expensive)"""
        img_id = random.choice(self.image_ids)

        with self.client.get(
            f"/images/{img_id}/filters",
            catch_response=True,
            name="Filter Analysis"
        ) as response:
            if response.status_code not in [200, 500]:
                response.failure(f"Filter analysis failed: {response.status_code}")
            elif response.status_code == 200:
                elapsed = response.elapsed.total_seconds()
                if elapsed > 25:
                    response.failure(f"Filter analysis took {elapsed:.1f}s (>25s)")
                elif elapsed > 20:
                    print(f"⚠️  Filter analysis took {elapsed:.1f}s (warning threshold)")
