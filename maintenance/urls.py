from django.urls import path
from . import views

app_name = 'maintenance'

urlpatterns = [
    path('', views.lista_atenciones, name='lista_atenciones'),
    path('<int:ticket_pk>/iniciar/', views.iniciar_atencion, name='iniciar_atencion'),
    path('<int:ticket_pk>/atender/', views.registrar_atencion, name='registrar_atencion'),
    path('<int:ticket_pk>/finalizar/', views.finalizar_atencion, name='finalizar_atencion'),
    path('<int:ticket_pk>/revisar/', views.revisar_atencion, name='revisar_atencion'),
]