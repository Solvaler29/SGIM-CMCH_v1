from django.http import JsonResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .models import Equipment


@login_required
def consultar_equipo(request, qr_identifier):
    """
    Consulta un equipo por su identificador QR.
    Nunca se conecta directamente a PostgreSQL desde el navegador;
    Django valida y realiza la consulta.
    """
    try:
        equipo = Equipment.objects.get(qr_identifier=qr_identifier)
        return JsonResponse({
            'encontrado': True,
            'datos': equipo.datos_basicos,
        })
    except Equipment.DoesNotExist:
        return JsonResponse({
            'encontrado': False,
            'mensaje': f'No se encontró un equipo con el código QR: {qr_identifier}',
        }, status=404)


@login_required
def lista_equipos(request):
    """Lista de equipos simulados (para pruebas sin cámara)."""
    equipos = Equipment.objects.all().order_by('nombre')
    return render(request, 'equipment/lista_equipos.html', {'equipos': equipos})