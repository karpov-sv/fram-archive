"""
URL configuration for archive project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, reverse_lazy
from django.conf import settings
from django.http import HttpResponse

from django.contrib.auth import views as auth_views

from . import views
from . import views_images
from . import views_photometry

urlpatterns = [
    # Index
    path(r'', views.index, name="index"),

    # Images
    path(r'images/', views_images.images_list, name='images'),

    # Nights
    path(r'nights/', views_images.images_nights, name='nights'),

    # Detailed image view
    path(r'images/<int:id>/', views_images.image_details, name='image_details'),
    path(r'images/<int:id>/download', views_images.image_download, name='image_download'),
    path(r'images/<int:id>/download/processed', views_images.image_download, {'raw':False}, name='image_download_processed'),
    path(r'images/<int:id>/full', views_images.image_preview, name='image_full'),
    path(r'images/<int:id>/view', views_images.image_preview, {'size':800}, name='image_view'),
    path(r'images/<int:id>/preview', views_images.image_preview, {'size':128}, name='image_preview'),
    # Image analysis
    path(r'images/<int:id>/bg', views_images.image_analysis, {'mode':'bg'}, name='image_bg'),
    path(r'images/<int:id>/fwhm', views_images.image_analysis, {'mode':'fwhm'}, name='image_fwhm'),
    path(r'images/<int:id>/wcs', views_images.image_analysis, {'mode':'wcs'}, name='image_wcs'),
    path(r'images/<int:id>/filters', views_images.image_analysis, {'mode':'filters'}, name='image_filters'),
    path(r'images/<int:id>/zero', views_images.image_analysis, {'mode':'zero'}, name='image_zero'),

    # Cutouts
    path(r'images/cutouts/', views_images.images_cutouts, name='images_cutouts'),
    path(r'images/<int:id>/cutout', views_images.image_cutout, name='image_cutout'),
    path(r'images/<int:id>/cutout/preview', views_images.image_cutout, {'size':300}, name='image_cutout_preview'),
    path(r'images/<int:id>/cutout/download', views_images.image_cutout, {'mode':'download'}, name='image_cutout_download'),

    # Photometry
    # path(r'photometry/?', views_photometry.photometry, name='photometry'),
    path(r'photometry/lc', views_photometry.lc, {'mode': 'jpeg'}, name='photometry_lc'),
    path(r'photometry/json', views_photometry.lc, {'mode': 'json'}, name='photometry_json'),
    path(r'photometry/text', views_photometry.lc, {'mode': 'text'}, name='photometry_text'),
    path(r'photometry/mjd', views_photometry.lc, {'mode': 'mjd'}, name='photometry_mjd'),

    # Search
    path(r'search/', views.search, name='search'),
    path(r'search/cutouts/', views.search, {'mode':'cutouts'}, name='search_cutouts'),
    path(r'search/photometry/', views.search, {'mode':'photometry'}, name='search_photometry'),

    # Auth
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('password/', auth_views.PasswordChangeView.as_view(success_url=reverse_lazy('password_change_done')), name='password'),
    path('password/done/', auth_views.PasswordChangeDoneView.as_view(), name='password_change_done'),

    # Robots
    path(r'robots.txt', lambda r: HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")),

    # Admin panel
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    from debug_toolbar.toolbar import debug_toolbar_urls
    urlpatterns = urlpatterns + debug_toolbar_urls()
