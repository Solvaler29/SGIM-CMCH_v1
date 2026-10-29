from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from tickets.models import Ticket
from django.db.models import Count, Q

@login_required
def dashboard(request):
    """Panel principal según el rol del usuario."""
    user = request.user
    context = {'usuario': user}
    context['es_administrador'] = user.tiene_rol('administrador')
    context['total_tickets'] = 0
    context['pendientes'] = 0
    context['en_atencion'] = 0
    context['cerrados'] = 0

    if user.tiene_rol('solicitante'):
        tickets = Ticket.objects.filter(solicitante=user).order_by('-created_at')[:10]
        context['tickets'] = tickets
        context['titulo'] = 'Mis Incidencias'
    elif user.tiene_rol('supervisor'):
        areas = user.areas.all()
        tickets = Ticket.objects.filter(area_soporte__in=areas).order_by('-created_at')[:10]
        context['tickets'] = tickets
        context['areas'] = areas
        context['titulo'] = 'Bandeja del Área'
    elif user.tiene_rol('tecnico'):
        asignaciones = user.asignaciones_tecnico.filter(activo=True)
        tickets = [a.ticket for a in asignaciones]
        context['tickets'] = tickets
        context['titulo'] = 'Mis Tareas Asignadas'
    else:  # administrador
        tickets = Ticket.objects.all().order_by('-created_at')[:10]
        context['tickets'] = tickets
        context['titulo'] = 'Panel de Administración'


    estadisticas = Ticket.objects.aggregate(
        total=Count('id'),
        pendientes=Count('id', filter=Q(estado='registrada')),
        en_atencion=Count('id', filter=Q(estado='en_atencion')),
        cerrados=Count('id', filter=Q(estado='cerrada_tecnicamente')),
    )

    context.update({
        'total_tickets': estadisticas['total'],
        'pendientes': estadisticas['pendientes'],
        'en_atencion': estadisticas['en_atencion'],
        'cerrados': estadisticas['cerrados'],
    })

    return render(request, 'core/dashboard.html', context)