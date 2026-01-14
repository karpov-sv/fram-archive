"""
Cache Tester Scenario

Tests cache effectiveness by requesting same resources twice
Validates that cache hits are faster than cache misses
Useful for monitoring cache performance under load
"""
from locust import HttpUser, task, between
import time

from locust_tests.config.credentials import Credentials
from locust_tests.utils.data_helpers import get_random_image_ids


class CacheTesterUser(HttpUser):
    """Tests cache effectiveness through repeated requests"""

    wait_time = between(1, 3)  # Quick repetition to test cache
    weight = 5  # Small percentage for cache monitoring

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

        # Use same image IDs to test caching
        self.image_ids = get_random_image_ids(10, id_range=(1, 1000))

    @task(5)
    def test_preview_cache(self):
        """Test image preview caching"""
        # Use same image ID to test cache
        img_id = self.image_ids[0]

        # First request (likely cache miss or stale cache)
        start = time.time()
        with self.client.get(
            f"/images/{img_id}/view",
            catch_response=True,
            name="Preview (first)"
        ) as response:
            first_time = time.time() - start

            if response.status_code != 200:
                response.failure(f"First request failed: {response.status_code}")
                return

        # Wait a bit
        time.sleep(0.5)

        # Second request (should be cached)
        start = time.time()
        with self.client.get(
            f"/images/{img_id}/view",
            catch_response=True,
            name="Preview (cached)"
        ) as response:
            second_time = time.time() - start

            if response.status_code != 200:
                response.failure(f"Cached request failed: {response.status_code}")
                return

            # Cache should make it faster
            if second_time >= first_time:
                response.failure(
                    f"Cache not effective: "
                    f"first={first_time:.3f}s, cached={second_time:.3f}s"
                )
            else:
                speedup = first_time / second_time if second_time > 0 else 0
                print(f"✓ Cache speedup: {speedup:.1f}x "
                      f"(first={first_time:.3f}s, cached={second_time:.3f}s)")

    @task(3)
    def test_nights_cache(self):
        """Test nights list caching (should be heavily cached)"""
        # First request
        start = time.time()
        with self.client.get("/nights/", name="Nights (first)") as response:
            first_time = time.time() - start
            if response.status_code != 200:
                return

        time.sleep(0.5)

        # Second request
        start = time.time()
        with self.client.get(
            "/nights/",
            catch_response=True,
            name="Nights (cached)"
        ) as response:
            second_time = time.time() - start

            if response.status_code != 200:
                response.failure("Cached nights failed")
                return

            # Should be significantly faster
            if second_time < 0.1:
                print(f"✓ Nights heavily cached: {second_time*1000:.1f}ms")
            elif second_time >= first_time:
                response.failure(
                    f"Nights cache not working: "
                    f"first={first_time:.3f}s, cached={second_time:.3f}s"
                )

    @task(2)
    def test_full_image_cache(self):
        """Test full image caching"""
        img_id = self.image_ids[1]

        # First request
        start = time.time()
        with self.client.get(f"/images/{img_id}/full", name="Full (first)") as response:
            first_time = time.time() - start
            if response.status_code != 200:
                return

        time.sleep(1)

        # Second request
        start = time.time()
        with self.client.get(
            f"/images/{img_id}/full",
            catch_response=True,
            name="Full (cached)"
        ) as response:
            second_time = time.time() - start

            if response.status_code != 200:
                response.failure("Cached full image failed")
                return

            if second_time < first_time:
                speedup = first_time / second_time if second_time > 0 else 0
                print(f"✓ Full image cache: {speedup:.1f}x speedup")
            else:
                response.failure(
                    f"Full image cache ineffective: "
                    f"first={first_time:.3f}s, cached={second_time:.3f}s"
                )
