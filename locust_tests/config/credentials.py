"""
Credential management for Locust load testing

SECURITY: Never commit actual credentials to version control!
Use environment variables or .env files (in .gitignore)
"""
import os
from decouple import Config, RepositoryEnv

# Load from .env.test file specifically
config_file = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    '.env.test'
)
config = Config(RepositoryEnv(config_file))


class Credentials:
    """Manage test credentials from environment variables"""

    @staticmethod
    def get_credentials():
        """
        Get test credentials from environment

        Returns:
            dict with username and password

        Raises:
            ValueError: If credentials are not configured
        """
        username = config('TEST_USERNAME', default=None)
        password = config('TEST_PASSWORD', default=None)

        if not username or not password:
            raise ValueError(
                "Test credentials not configured. "
                "Set TEST_USERNAME and TEST_PASSWORD in .env.test file or environment"
            )

        if username == 'locust_test_user' or password == 'change_me_to_secure_password':
            print(
                "\n⚠️  WARNING: Using default test credentials. "
                "Update TEST_USERNAME and TEST_PASSWORD in .env.test\n"
            )

        return {
            'username': username,
            'password': password
        }

    @staticmethod
    def get_csrf_token(response):
        """
        Extract CSRF token from response cookies

        Args:
            response: Locust response object

        Returns:
            CSRF token string or None
        """
        return response.cookies.get('csrftoken', None)

    @staticmethod
    def login(client, credentials=None):
        """
        Perform login with test credentials

        Args:
            client: Locust HttpSession client
            credentials: Optional dict with username/password

        Returns:
            bool: True if login successful

        Raises:
            Exception: If login fails
        """
        if credentials is None:
            credentials = Credentials.get_credentials()

        # Get login page to obtain CSRF token
        response = client.get('/login/', name='Login page')

        if response.status_code != 200:
            raise Exception(f"Login page returned {response.status_code}")

        csrf_token = Credentials.get_csrf_token(response)

        if not csrf_token:
            raise Exception("No CSRF token in login page")

        # Perform login
        login_data = {
            'username': credentials['username'],
            'password': credentials['password'],
            'csrfmiddlewaretoken': csrf_token,
        }

        response = client.post(
            '/login/',
            data=login_data,
            headers={'Referer': client.base_url + '/login/'},
            name='Login POST',
            allow_redirects=False
        )

        # Check if login was successful (redirect or 200)
        success = response.status_code in [200, 302]

        if not success:
            raise Exception(
                f"Login failed with status {response.status_code}. "
                f"Check credentials in .env.test"
            )

        return success


def validate_credentials():
    """
    Validate that credentials are configured

    Raises:
        ValueError: If credentials are invalid
    """
    try:
        creds = Credentials.get_credentials()
        print(f"✓ Credentials configured for user: {creds['username']}")
        return True
    except ValueError as e:
        print(f"✗ Credential validation failed: {e}")
        return False


if __name__ == '__main__':
    # Validate credentials when run directly
    validate_credentials()
