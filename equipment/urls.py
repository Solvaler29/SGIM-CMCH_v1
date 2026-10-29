from django.urls import path
from . import views

app_name = 'equipment'

urlpatterns = [
    path('consultar/<str:qr_identifier>/', views.consultar_equipo, name='consultar_equipo'),
    path('lista/', views.lista_equipos, name='lista_equipos'),
]