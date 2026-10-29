from django.urls import path
from . import views

app_name = 'tickets'

urlpatterns = [
    path('', views.lista_tickets, name='lista_tickets'),
    path('registrar/', views.registrar_ticket, name='registrar_ticket'),
    path('<int:pk>/', views.detalle_ticket, name='detalle_ticket'),
    path('<int:pk>/redirigir/', views.redirigir_ticket, name='redirigir_ticket'),
    path('<int:pk>/priorizar/', views.priorizar_ticket, name='priorizar_ticket'),
    path('<int:pk>/asignar/', views.asignar_tecnico, name='asignar_tecnico'),
]