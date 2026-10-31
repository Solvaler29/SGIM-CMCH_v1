from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from tickets.models import Ticket
from django.db.models import Count, Q

@login_required
def dashboard(request):
    """Panel principal adaptado al rol del usuario."""
    user = request.user
    context = {'usuario': user}
    context['es_administrador'] = user.tiene_rol('administrador')

    if user.tiene_rol('solicitante'):
        tickets_qs = Ticket.objects.filter(solicitante=user)
        context['tickets'] = tickets_qs.order_by('-created_at')[:10]
        context['titulo'] = 'Mis Incidencias Reportadas'
    elif user.tiene_rol('supervisor'):
        areas = user.areas.all()
        tickets_qs = Ticket.objects.filter(Q(area_soporte__in=areas) | Q(solicitante=user)).distinct()
        context['tickets'] = tickets_qs.order_by('-created_at')[:10]
        context['areas'] = areas
        context['titulo'] = 'Bandeja del Área Asignada'
    elif user.tiene_rol('tecnico'):
        tickets_qs = Ticket.objects.filter(Q(asignaciones__tecnico=user, asignaciones__activo=True) | Q(solicitante=user)).distinct()
        context['tickets'] = tickets_qs.order_by('-created_at')[:10]
        context['titulo'] = 'Mis Tareas y Atenciones'
    else:  # administrador
        tickets_qs = Ticket.objects.all()
        context['tickets'] = tickets_qs.order_by('-created_at')[:10]
        context['titulo'] = 'Panel de Control Hospitalario'

    estadisticas = tickets_qs.aggregate(
        total=Count('id'),
        pendientes=Count('id', filter=Q(estado__in=['registrada', 'revision'])),
        en_atencion=Count('id', filter=Q(estado__in=['asignada', 'en_atencion', 'pendiente_validacion'])),
        cerrados=Count('id', filter=Q(estado='cerrada_tecnicamente')),
    )

    context.update({
        'total_tickets': estadisticas['total'] or 0,
        'pendientes': estadisticas['pendientes'] or 0,
        'en_atencion': estadisticas['en_atencion'] or 0,
        'cerrados': estadisticas['cerrados'] or 0,
    })

    return render(request, 'core/dashboard.html', context)
