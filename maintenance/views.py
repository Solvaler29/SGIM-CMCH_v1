from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from tickets.models import Ticket, TicketEvent
from maintenance.models import AtencionTecnica, RevisionSupervisor


@login_required
def lista_atenciones(request):
    user = request.user
    if user.tiene_rol('tecnico'):
        atenciones = AtencionTecnica.objects.filter(tecnico=user).order_by('-creado_en')
    elif user.tiene_rol('supervisor') or user.tiene_rol('administrador'):
        atenciones = AtencionTecnica.objects.all().order_by('-creado_en')
    else:
        atenciones = AtencionTecnica.objects.none()
    return render(request, 'maintenance/lista_atenciones.html', {'atenciones': atenciones})


@login_required
def iniciar_atencion(request, ticket_pk):
    if not request.user.tiene_rol('tecnico'):
        messages.error(request, 'Solo el técnico puede iniciar una atención.')
        return redirect('tickets:detalle_ticket', pk=ticket_pk)
    ticket = get_object_or_404(Ticket, pk=ticket_pk)
    if not ticket.asignaciones.filter(tecnico=request.user, activo=True).exists():
        messages.error(request, 'Este ticket no está asignado a ti.')
        return redirect('tickets:detalle_ticket', pk=ticket_pk)
    atencion, creada = AtencionTecnica.objects.get_or_create(
        ticket=ticket,
        tecnico=request.user,
        defaults={'work_started_at': timezone.now()},
    )
    if not creada and not atencion.work_started_at:
        atencion.work_started_at = timezone.now()
        atencion.save()
    ticket.estado = 'en_atencion'
    ticket.save()
    TicketEvent.objects.create(
        ticket=ticket,
        tipo_accion='inicio_atencion',
        usuario=request.user,
        detalles='Técnico inició la atención real del trabajo.',
    )


@login_required
def registrar_atencion(request, ticket_pk):
    if not request.user.tiene_rol('tecnico'):
        messages.error(request, 'Solo el técnico puede registrar la atención.')
        return redirect('tickets:detalle_ticket', pk=ticket_pk)
    ticket = get_object_or_404(Ticket, pk=ticket_pk)
    atencion = get_object_or_404(AtencionTecnica, ticket=ticket, tecnico=request.user)
    if request.method == 'POST':
        atencion.diagnostico = request.POST.get('diagnostico', '')
        atencion.acciones_realizadas = request.POST.get('acciones_realizadas', '')
        atencion.observaciones = request.POST.get('observaciones', '')
        atencion.materiales_requeridos = request.POST.get('materiales_requeridos', '')
        atencion.recursos_utilizados = request.POST.get('recursos_utilizados', '')
        atencion.evidencias = request.POST.get('evidencias', '')
        atencion.save()
        TicketEvent.objects.create(
            ticket=ticket,
            tipo_accion='materiales_registrados',
            usuario=request.user,
            detalles='Diagnóstico, acciones y recursos registrados.',
        )
        messages.success(request, 'Información de atención guardada.')
        return redirect('tickets:detalle_ticket', pk=ticket_pk)
    return render(request, 'maintenance/registrar_atencion.html', {
        'ticket': ticket, 'atencion': atencion
    })


@login_required
def finalizar_atencion(request, ticket_pk):
    if not request.user.tiene_rol('tecnico'):
        messages.error(request, 'Solo el técnico puede finalizar una atención.')
        return redirect('tickets:detalle_ticket', pk=ticket_pk)
    ticket = get_object_or_404(Ticket, pk=ticket_pk)
    atencion = get_object_or_404(AtencionTecnica, ticket=ticket, tecnico=request.user)
    atencion.work_finished_at = timezone.now()
    atencion.finalizado_por_tecnico = True
    atencion.enviado_a_revision = True
    atencion.save()
    ticket.estado = 'pendiente_validacion'
    ticket.save()
    TicketEvent.objects.create(
        ticket=ticket,
        tipo_accion='fin_atencion',
        usuario=request.user,
        detalles='Técnico declaró finalizada la intervención. Enviado a revisión del supervisor.',
    )
    messages.success(request, 'Intervención finalizada y enviada a revisión del supervisor.')
    return redirect('tickets:detalle_ticket', pk=ticket_pk)


@login_required
@user_passes_test(lambda u: u.tiene_rol('supervisor') or u.tiene_rol('administrador'))
def revisar_atencion(request, ticket_pk):
    ticket = get_object_or_404(Ticket, pk=ticket_pk)
    atencion = get_object_or_404(AtencionTecnica, ticket=ticket)
    if request.method == 'POST':
        decision = request.POST.get('decision')
        justificacion = request.POST.get('justificacion', '')
        RevisionSupervisor.objects.create(
            atencion=atencion,
            supervisor=request.user,
            decision=decision,
            justificacion=justificacion,
        )
        if decision == 'aprobado':
            ticket.estado = 'cerrada_tecnicamente'
            ticket.closed_at = timezone.now()
            ticket.save()
            TicketEvent.objects.create(
                ticket=ticket,
                tipo_accion='aprobacion',
                usuario=request.user,
                detalles=f'Cierre aprobado por el supervisor. Justificación: {justificacion}',
            )
            messages.success(request, 'Atención aprobada y ticket cerrado técnicamente.')
        else:
            ticket.estado = 'devuelta'
            ticket.save()
            TicketEvent.objects.create(
                ticket=ticket,
                tipo_accion='devolucion',
                usuario=request.user,
                detalles=f'Devuelto para corrección. Justificación: {justificacion}',
            )
            messages.warning(request, 'Atención devuelta para correcciones.')
        return redirect('tickets:detalle_ticket', pk=ticket_pk)
    return render(request, 'maintenance/revisar_atencion.html', {
        'ticket': ticket, 'atencion': atencion
    })
    messages.success(request, 'Atención iniciada. Fecha y hora registradas en el servidor.')
    return redirect('tickets:detalle_ticket', pk=ticket_pk)