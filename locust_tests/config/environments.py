"""
Environment configurations for Locust load testing

Supports local, staging, and production environments
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Environment:
    """Environment configuration for load testing"""
    name: str
    host: str
    users: int
    spawn_rate: int
    run_time: str
    description: str = ""

    def __str__(self):
        return f"{self.name}: {self.host} ({self.users} users)"


# Environment definitions
ENVIRONMENTS = {
    'local': Environment(
        name='local',
        host='http://localhost:18000',
        users=10,
        spawn_rate=2,
        run_time='5m',
        description='Local development environment'
    ),
    'staging': Environment(
        name='staging',
        host=os.getenv('STAGING_HOST', 'http://staging.fram.example.com'),
        users=50,
        spawn_rate=5,
        run_time='15m',
        description='Staging environment for pre-production testing'
    ),
    'production': Environment(
        name='production',
        host=os.getenv('PROD_HOST', 'https://pc048b.fzu.cz/archive/'),
        users=100,
        spawn_rate=10,
        run_time='30m',
        description='Production environment (use with caution!)'
    ),
    'stress': Environment(
        name='stress',
        host=os.getenv('TEST_HOST', 'http://localhost:18000'),
        users=200,
        spawn_rate=20,
        run_time='1h',
        description='Stress testing to find breaking point'
    ),
}


def get_environment(env_name: Optional[str] = None) -> Environment:
    """
    Get environment configuration by name

    Args:
        env_name: Environment name (local, staging, production, stress)
                  If None, reads from LOCUST_ENV environment variable

    Returns:
        Environment configuration

    Raises:
        ValueError: If environment name is invalid
    """
    if env_name is None:
        env_name = os.getenv('LOCUST_ENV', 'local')

    env_name = env_name.lower()

    if env_name not in ENVIRONMENTS:
        available = ', '.join(ENVIRONMENTS.keys())
        raise ValueError(
            f"Invalid environment '{env_name}'. "
            f"Available: {available}"
        )

    return ENVIRONMENTS[env_name]


def list_environments():
    """Print available environments"""
    print("\nAvailable environments:")
    print("-" * 60)
    for name, env in ENVIRONMENTS.items():
        print(f"  {name:12} - {env.host}")
        print(f"               Users: {env.users}, Spawn rate: {env.spawn_rate}")
        print(f"               {env.description}")
        print()


if __name__ == '__main__':
    # Print available environments when run directly
    list_environments()
