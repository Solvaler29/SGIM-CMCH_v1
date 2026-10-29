from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.dashboard_reportes, name='dashboard_reportes'),
]