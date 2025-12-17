from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Permission, User

from django.core.management.base import BaseCommand, CommandError

from archive import models


class Command(BaseCommand):
    help = 'Creates default permissions'

    def createPermission(self, model, name, title):
        content_type = ContentType.objects.get_for_model(model)

        print(f"Creating permission {name}: {title}")

        if Permission.objects.filter(codename=name, content_type=content_type):
            print(f"Permission already exists")
            return

        Permission.objects.create(
            codename=name,
            name=title,
            content_type=content_type
        )

    def handle(self, *args, **kwargs):
        self.createPermission(User, 'can_view_images', 'Can view images')
        self.createPermission(User, 'can_analyze_images', 'Can analyze images')
