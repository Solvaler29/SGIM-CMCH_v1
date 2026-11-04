"""Configuración de URLs del proyecto SGIM-CMCH."""
from django.contrib import admin
from django.urls import path, include
from django.views.decorators.http import require_POST

urlpatterns = [
    # Django 4.2 aún permite GET en su LogoutView; conservar la vista admin,
    # pero exigir POST también cuando se accede directamente a esta URL.
    path('admin/logout/', require_POST(admin.site.logout)),
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('equipment/', include('equipment.urls')),
    path('tickets/', include('tickets.urls')),
    path('maintenance/', include('maintenance.urls')),
    path('reports/', include('reports.urls')),
]
