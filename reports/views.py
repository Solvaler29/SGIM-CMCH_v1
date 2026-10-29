from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Avg, F, ExpressionWrapper, DurationField
from django.utils import timezone
from datetime import timedelta
from tickets.models import Ticket, TicketEvent, Satisfaccion
from accounts.models import Area, User


@login_required
@user_passes_test(lambda u: u.tiene_rol('supervisor') or u.tiene_rol('tecnico') or u.tiene_rol('administrador'))
def dashboard_reportes(request):
    """Panel de reportes con datos reales de PostgreSQL."""
    user = request.user

    # Filtro por área según permisos
    if user.tiene_rol('administrador'):
        tickets_qs = Ticket.objects.all()
    elif user.tiene_rol('supervisor'):
        tickets_qs = Ticket.objects.filter(area_soporte__in=user.areas.all())
    elif user.tiene_rol('tecnico'):
        tickets_qs = Ticket.objects.filter(asignaciones__tecnico=user, asignaciones__activo=True)
    else:
        tickets_qs = Ticket.objects.none()

    # Indicadores
    pendientes = tickets_qs.filter(estado='registrada').count()
    en_revision = tickets_qs.filter(estado='revision').count()
    asignadas = tickets_qs.filter(estado='asignada').count()
    en_atencion = tickets_qs.filter(estado='en_atencion').count()
    pendiente_validacion = tickets_qs.filter(estado='pendiente_validacion').count()
    devueltas = tickets_qs.filter(estado='devuelta').count()
    cerradas = tickets_qs.filter(estado='cerrada_tecnicamente').count()

    # Tickets por mes (últimos 6 meses)
    hoy = timezone.now()
    meses = []
    for i in range(5, -1, -1):
        mes_inicio = (hoy - timedelta(days=30 * i)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        mes_fin = (mes_inicio + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
        count = tickets_qs.filter(created_at__range=(mes_inicio, mes_fin)).count()
        meses.append({'mes': mes_inicio.strftime('%Y-%m'), 'cantidad': count})

    # Tickets por servicio
    por_servicio = list(
        tickets_qs.values('servicio__nombre')
        .annotate(total=Count('id'))
        .order_by('-total')
    )

    # Tickets por prioridad
    por_prioridad = list(
        tickets_qs.values('prioridad')
        .annotate(total=Count('id'))
        .order_by('-total')
    )

    # Tiempo de respuesta (creado -> asignado) en horas
    tickets_con_asignacion = tickets_qs.exclude(scheduled_at__isnull=True)
    if tickets_con_asignacion.exists():
        resp_expr = ExpressionWrapper(
            F('scheduled_at') - F('created_at'),
            output_field=DurationField(),
        )
        tiempo_respuesta_promedio = tickets_con_asignacion.annotate(
            duracion=resp_expr
        ).aggregate(promedio=Avg('duracion'))['promedio']
        tiempo_respuesta_horas = round(tiempo_respuesta_promedio.total_seconds() / 3600, 2) if tiempo_respuesta_promedio else 0
    else:
        tiempo_respuesta_horas = 0

    # Tiempo de solución (creado -> cerrado) en horas
    tickets_cerrados = tickets_qs.exclude(closed_at__isnull=True)
    if tickets_cerrados.exists():
        sol_expr = ExpressionWrapper(
            F('closed_at') - F('created_at'),
            output_field=DurationField(),
        )
        tiempo_solucion_promedio = tickets_cerrados.annotate(
            duracion=sol_expr
        ).aggregate(promedio=Avg('duracion'))['promedio']
        tiempo_solucion_horas = round(tiempo_solucion_promedio.total_seconds() / 3600, 2) if tiempo_solucion_promedio else 0
    else:
        tiempo_solucion_horas = 0

    # Satisfacción promedio
    encuestas = Satisfaccion.objects.filter(ticket__in=tickets_qs)
    satisfaccion_promedio = encuestas.aggregate(promedio=Avg('puntuacion'))['promedio']
    satisfaccion_promedio = round(satisfaccion_promedio, 2) if satisfaccion_promedio else 0

    context = {
        'pendientes': pendientes,
        'en_revision': en_revision,
        'asignadas': asignadas,
        'en_atencion': en_atencion,
        'pendiente_validacion': pendiente_validacion,
        'devueltas': devueltas,
        'cerradas': cerradas,
        'meses': meses,
        'por_servicio': por_servicio,
        'por_prioridad': por_prioridad,
        'tiempo_respuesta_horas': tiempo_respuesta_horas,
        'tiempo_solucion_horas': tiempo_solucion_horas,
        'satisfaccion_promedio': satisfaccion_promedio,
        'total_tickets': tickets_qs.count(),
    }
    return render(request, 'reports/dashboard_reportes.html', context)