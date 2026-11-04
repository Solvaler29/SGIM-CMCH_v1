from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.http import Http404, HttpResponse
from tickets.models import Ticket
from tickets.transactions import controlar_conflictos
from tickets.models import TicketEvent
from maintenance.models import AtencionTecnica, RevisionSupervisor
from tickets.permissions import (
    REVISAR_ATENCION, INICIAR_ATENCION, EDITAR_ATENCION, FINALIZAR_ATENCION,
    tickets_para_usuario, obtener_ticket_autorizado, obtener_contexto_atencion_autorizado,
)


@login_required
def lista_atenciones(request):
    user = request.user
    if user.tiene_rol('tecnico'):
        atenciones = AtencionTecnica.objects.filter(tecnico=user).order_by('-creado_en')
    elif user.tiene_rol('supervisor') or user.tiene_rol('administrador'):
        atenciones = AtencionTecnica.objects.filter(
            ticket__in=tickets_para_usuario(user, REVISAR_ATENCION),
        ).order_by('-creado_en')
    else:
        atenciones = AtencionTecnica.objects.none()
    return render(request, 'maintenance/lista_atenciones.html', {'atenciones': atenciones})


@login_required
@require_POST
@controlar_conflictos
def iniciar_atencion(request, ticket_pk):
    with transaction.atomic():
        ticket, atencion = obtener_contexto_atencion_autorizado(
            request.user, ticket_pk, INICIAR_ATENCION, bloquear=True,
        )
        if atencion is None:
            atencion = AtencionTecnica.objects.create(
                ticket=ticket, tecnico=request.user, work_started_at=timezone.now(),
            )
        elif not atencion.work_started_at:
            atencion.work_started_at = timezone.now()
            atencion.save(update_fields=['work_started_at', 'actualizado_en'])
        ticket.estado = 'en_atencion'
        ticket.save(update_fields=['estado'])
        TicketEvent.objects.create(
            ticket=ticket, tipo_accion='inicio_atencion', usuario=request.user,
            detalles='Técnico inició la atención real del trabajo.',
        )
    messages.success(request, 'Atención iniciada. Fecha y hora registradas en el servidor.')
    return redirect('tickets:detalle_ticket', pk=ticket_pk)


CAMPOS_ATENCION = (
    'diagnostico', 'acciones_realizadas', 'observaciones',
    'materiales_requeridos', 'recursos_utilizados', 'evidencias',
)


@login_required
@controlar_conflictos
def registrar_atencion(request, ticket_pk):
    if request.method == 'POST':
        with transaction.atomic():
            ticket, atencion = obtener_contexto_atencion_autorizado(
                request.user, ticket_pk, EDITAR_ATENCION, bloquear=True,
            )
            valores = {campo: request.POST.get(campo, '') for campo in CAMPOS_ATENCION}
            if any(getattr(atencion, campo) != valor for campo, valor in valores.items()):
                for campo, valor in valores.items():
                    setattr(atencion, campo, valor)
                atencion.save(update_fields=[*CAMPOS_ATENCION, 'actualizado_en'])
                TicketEvent.objects.create(
                    ticket=ticket, tipo_accion='materiales_registrados', usuario=request.user,
                    detalles='Diagnóstico, acciones y recursos registrados.',
                )
        messages.success(request, 'Información de atención guardada.')
        return redirect('tickets:detalle_ticket', pk=ticket_pk)
    ticket, atencion = obtener_contexto_atencion_autorizado(
        request.user, ticket_pk, EDITAR_ATENCION,
    )
    return render(request, 'maintenance/registrar_atencion.html', {
        'ticket': ticket, 'atencion': atencion,
    })


@login_required
@require_POST
@controlar_conflictos
def finalizar_atencion(request, ticket_pk):
    with transaction.atomic():
        ticket, atencion = obtener_contexto_atencion_autorizado(
            request.user, ticket_pk, FINALIZAR_ATENCION, bloquear=True,
        )
        atencion.work_finished_at = timezone.now()
        atencion.finalizado_por_tecnico = True
        atencion.enviado_a_revision = True
        atencion.save(update_fields=[
            'work_finished_at', 'finalizado_por_tecnico', 'enviado_a_revision', 'actualizado_en',
        ])
        ticket.estado = 'pendiente_validacion'
        ticket.save(update_fields=['estado'])
        TicketEvent.objects.create(
            ticket=ticket, tipo_accion='fin_atencion', usuario=request.user,
            detalles='Técnico declaró finalizada la intervención. Enviado a revisión del supervisor.',
        )
    messages.success(request, 'Intervención finalizada y enviada a revisión del supervisor.')
    return redirect('tickets:detalle_ticket', pk=ticket_pk)


def _atencion_unica(ticket):
    atenciones = list(AtencionTecnica.objects.filter(ticket=ticket)[:2])
    if len(atenciones) != 1:
        # No elegir una intervencion arbitraria ni resolver aqui AUD-006/007.
        raise Http404
    return atenciones[0]


def _registrar_revision(ticket, atencion, decision, justificacion, supervisor):
    estado_destino = 'cerrada_tecnicamente' if decision == 'aprobado' else 'devuelta'
    anterior = atencion.revisiones.order_by('-fecha_decision', '-pk').first()
    if (anterior and anterior.decision == decision and anterior.justificacion == justificacion
            and ticket.estado == estado_destino):
        return False
    if ticket.closed_at is not None or ticket.estado == 'cerrada_tecnicamente':
        # Una segunda solicitud no debe reabrir ni volver a fechar un cierre.
        return None
    RevisionSupervisor.objects.create(
        atencion=atencion, supervisor=supervisor, decision=decision, justificacion=justificacion,
    )
    ticket.estado = estado_destino
    campos = ['estado']
    if decision == 'aprobado':
        ticket.closed_at = timezone.now()
        campos.append('closed_at')
    ticket.save(update_fields=campos)
    TicketEvent.objects.create(
        ticket=ticket, tipo_accion='aprobacion' if decision == 'aprobado' else 'devolucion',
        usuario=supervisor,
        detalles=(f'Cierre aprobado por el supervisor. Justificación: {justificacion}'
                  if decision == 'aprobado' else f'Devuelto para corrección. Justificación: {justificacion}'),
    )
    return True


@login_required
@controlar_conflictos
def revisar_atencion(request, ticket_pk):
    if request.method == 'POST':
        with transaction.atomic():
            ticket = obtener_ticket_autorizado(
                request.user, ticket_pk, REVISAR_ATENCION,
                queryset=Ticket.objects.select_for_update(),
            )
            atencion = _atencion_unica(ticket)
            decision = request.POST.get('decision')
            justificacion = request.POST.get('justificacion', '')
            if decision not in dict(RevisionSupervisor.DECISIONES):
                return HttpResponse('Selecciona una decisión válida.', status=400)
            guardada = _registrar_revision(ticket, atencion, decision, justificacion, request.user)
        if guardada is None:
            return HttpResponse('El ticket ya está cerrado. Actualiza la página.', status=409)
        if decision == 'aprobado':
            messages.success(request, 'Atención aprobada y ticket cerrado técnicamente.')
        else:
            messages.warning(request, 'Atención devuelta para correcciones.')
        return redirect('tickets:detalle_ticket', pk=ticket_pk)
    ticket = obtener_ticket_autorizado(request.user, ticket_pk, REVISAR_ATENCION)
    atencion = _atencion_unica(ticket)
    return render(request, 'maintenance/revisar_atencion.html', {
        'ticket': ticket, 'atencion': atencion,
    })
