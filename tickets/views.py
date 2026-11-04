from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import FileResponse, Http404, HttpResponse
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.utils import validate_file_name
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from pathlib import PurePosixPath
from equipment.models import Equipment
from .models import Ticket, TicketEvent, TicketAssignment
from .forms import TicketForm, TicketAssignmentForm
from .transactions import controlar_conflictos
from django.db import transaction, IntegrityError, OperationalError
from core.models import Servicio, AreaProblema
from accounts.models import Area, User
from .permissions import (
    CLASIFICAR, REDIRIGIR, ASIGNAR_TECNICO, REVISAR_ATENCION, VER_EVIDENCIA,
    INICIAR_ATENCION, EDITAR_ATENCION, FINALIZAR_ATENCION,
    tickets_para_usuario, obtener_ticket_autorizado, puede_operar_ticket,
    puede_registrar_incidencia,
)


TIPOS_IMAGEN_EVIDENCIA = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.webp': 'image/webp', '.gif': 'image/gif',
}


@never_cache
@login_required
@require_safe
def ver_evidencia(request, pk):
    """Entrega la fotografía desde su storage, después de autorizar el ticket."""
    ticket = obtener_ticket_autorizado(request.user, pk, VER_EVIDENCIA)
    fotografia = ticket.fotografia
    if not fotografia:
        raise Http404
    nombre = fotografia.name
    try:
        # El cliente solo elige un ticket, nunca una ruta. Validar también la
        # referencia persistida antes de entregarla al backend de almacenamiento.
        validate_file_name(nombre, allow_relative_path=True)
        if '\\' in nombre or ':' in nombre:
            raise SuspiciousFileOperation
        archivo = fotografia.storage.open(nombre, 'rb')
    except (OSError, SuspiciousFileOperation):
        raise Http404 from None
    extension = PurePosixPath(nombre).suffix.lower()
    tipo = TIPOS_IMAGEN_EVIDENCIA.get(extension)
    response = FileResponse(
        archivo, content_type=tipo or 'application/octet-stream',
        as_attachment=tipo is None, filename='evidencia' + (extension if tipo else '.bin'),
    )
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
def lista_tickets(request):
    tickets = tickets_para_usuario(request.user).order_by('-created_at')
    return render(request, 'tickets/lista_tickets.html', {'tickets': tickets})


@login_required
def registrar_ticket(request):
    if not puede_registrar_incidencia(request.user):
        raise Http404
    if request.method == 'POST':
        archivos = request.FILES.copy()
        captura = archivos.get('fotografia_camara')
        duplicada = bool(captura and archivos.get('fotografia'))
        if captura and not duplicada:
            archivos['fotografia'] = captura
        form = TicketForm(request.POST, archivos, solicitante=request.user)
        if duplicada:
            form.add_error('fotografia', 'Selecciona una sola fotografía: cámara o archivo.')
        if form.is_valid():
            from .codigos import LimiteCodigoTicket
            try:
                with transaction.atomic():
                    ticket = form.save(commit=False)
                    ticket.solicitante = request.user
                    ticket.save()
                    form.save_m2m()
                    TicketEvent.objects.create(
                        ticket=ticket, tipo_accion='registro', usuario=request.user,
                        detalles=f'Ticket registrado: {ticket.codigo_ticket}',
                    )
            except LimiteCodigoTicket as error:
                form.add_error(None, str(error))
                return render(request, 'tickets/registrar_ticket.html', {
                    'form': form, 'equipos_demo': Equipment.objects.all()[:20],
                }, status=409)
            messages.success(request, f'Incidencia registrada correctamente: {ticket.codigo_ticket}')
            return redirect('tickets:detalle_ticket', pk=ticket.pk)
    else:
        form = TicketForm(solicitante=request.user)
    equipos_demo = Equipment.objects.all()[:20]
    return render(request, 'tickets/registrar_ticket.html', {'form': form, 'equipos_demo': equipos_demo})


@login_required
def detalle_ticket(request, pk):
    ticket = obtener_ticket_autorizado(request.user, pk)
    eventos = ticket.eventos.all()
    asignaciones = ticket.asignaciones.all().order_by('-fecha_asignacion')
    asignacion_vigente = ticket.asignaciones.filter(activo=True).first()
    return render(request, 'tickets/detalle_ticket.html', {
        'ticket': ticket,
        'eventos': eventos,
        'asignaciones': asignaciones,
        'asignacion_vigente': asignacion_vigente,
        'puede_clasificar': puede_operar_ticket(request.user, ticket, CLASIFICAR),
        'puede_redirigir': puede_operar_ticket(request.user, ticket, REDIRIGIR),
        'puede_asignar': puede_operar_ticket(request.user, ticket, ASIGNAR_TECNICO),
        'puede_revisar': puede_operar_ticket(request.user, ticket, REVISAR_ATENCION),
        'puede_iniciar_atencion': puede_operar_ticket(request.user, ticket, INICIAR_ATENCION),
        'puede_editar_atencion': puede_operar_ticket(request.user, ticket, EDITAR_ATENCION),
        'puede_finalizar_atencion': puede_operar_ticket(request.user, ticket, FINALIZAR_ATENCION),
    })


@login_required
@controlar_conflictos
def redirigir_ticket(request, pk):
    if request.method == 'POST':
        with transaction.atomic():
            ticket = obtener_ticket_autorizado(
                request.user, pk, REDIRIGIR, queryset=Ticket.objects.select_for_update(),
            )
            if ticket.closed_at is not None or ticket.estado == 'cerrada_tecnicamente':
                return HttpResponse('El ticket ya está cerrado. Actualiza la página.', status=409)
            nueva_area_id = request.POST.get('area_soporte')
            nueva_area = get_object_or_404(Area, pk=nueva_area_id)
            if (ticket.area_soporte_id == nueva_area.pk and ticket.estado == 'revision'
                    and ticket.redirigido_de_id == ticket.pk):
                return redirect('tickets:detalle_ticket', pk=pk)
            area_anterior = ticket.area_soporte
            ticket.redirigido_de = ticket
            ticket.area_soporte = nueva_area
            ticket.estado = 'revision'
            ticket.save(update_fields=['redirigido_de', 'area_soporte', 'estado'])
            TicketEvent.objects.create(
                ticket=ticket,
                tipo_accion='redireccion',
                usuario=request.user,
                detalles=f'Redirigido de {area_anterior} a {nueva_area}',
            )
        messages.success(request, f'Ticket redirigido a {nueva_area.nombre}.')
        return redirect('tickets:detalle_ticket', pk=pk)
    ticket = obtener_ticket_autorizado(request.user, pk, REDIRIGIR)
    areas = Area.objects.filter(activa=True)
    return render(request, 'tickets/redirigir_ticket.html', {'ticket': ticket, 'areas': areas})


@login_required
@controlar_conflictos
def priorizar_ticket(request, pk):
    if request.method == 'POST':
        with transaction.atomic():
            ticket = obtener_ticket_autorizado(
                request.user, pk, CLASIFICAR, queryset=Ticket.objects.select_for_update(),
            )
            prioridad = request.POST.get('prioridad')
            if prioridad in dict(Ticket.PRIORIDADES) and prioridad != ticket.prioridad:
                anterior = ticket.prioridad
                ticket.prioridad = prioridad
                ticket.save(update_fields=['prioridad'])
                TicketEvent.objects.create(
                    ticket=ticket,
                    tipo_accion='cambio_prioridad',
                    usuario=request.user,
                    detalles=f'Prioridad cambiada de {anterior} a {prioridad}',
                )
        if prioridad in dict(Ticket.PRIORIDADES):
            messages.success(request, f'Prioridad actualizada a {ticket.get_prioridad_display()}.')
        return redirect('tickets:detalle_ticket', pk=pk)
    ticket = obtener_ticket_autorizado(request.user, pk, CLASIFICAR)
    return render(request, 'tickets/priorizar_ticket.html', {'ticket': ticket})


@login_required
def asignar_tecnico(request, pk):
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Serializar sobre el ticket, incluso si aún no hay asignación.
                ticket = obtener_ticket_autorizado(
                    request.user, pk, ASIGNAR_TECNICO,
                    queryset=Ticket.objects.select_for_update(),
                )
                form = TicketAssignmentForm(request.POST, ticket=ticket)
                valida = form.is_valid()
                if valida:
                    cambiada = _registrar_asignacion(
                        ticket, form.cleaned_data['tecnico'],
                        form.cleaned_data['scheduled_at'], request.user,
                    )
            if valida:
                messages.success(request, 'Asignación registrada.' if cambiada else 'La asignación ya está registrada.')
                return redirect('tickets:detalle_ticket', pk=pk)
        except (IntegrityError, OperationalError) as error:
            # Fuera de atomic: cualquier escritura previa ya fue revertida.
            causa = error.__cause__
            codigo = getattr(causa, 'pgcode', None)
            restriccion = getattr(getattr(causa, 'diag', None), 'constraint_name', None)
            if codigo not in ('40001', '40P01', '55P03') and not (
                codigo == '23505' and restriccion == 'uniq_ticket_asignacion_activa'
            ):
                raise
            ticket = obtener_ticket_autorizado(request.user, pk, ASIGNAR_TECNICO)
            form = TicketAssignmentForm(request.POST, ticket=ticket)
            form.is_valid()
            form.add_error(None, 'No se guardó la asignación por un conflicto concurrente. Actualiza e inténtalo nuevamente.')
            return render(request, 'tickets/asignar_tecnico.html', {
                'ticket': ticket, 'form': form, 'tecnicos': form.fields['tecnico'].queryset,
            }, status=409)
        status = 400
    else:
        ticket = obtener_ticket_autorizado(request.user, pk, ASIGNAR_TECNICO)
        vigente = ticket.asignaciones.filter(activo=True).first()
        form = TicketAssignmentForm(ticket=ticket, initial={
            'tecnico': vigente.tecnico_id if vigente else None,
            'scheduled_at': ticket.scheduled_at,
        })
        status = 200
    return render(request, 'tickets/asignar_tecnico.html', {
        'ticket': ticket, 'form': form, 'tecnicos': form.fields['tecnico'].queryset,
    }, status=status)


def _registrar_asignacion(ticket, tecnico, scheduled_at, autor):
    """Persistencia acotada: requiere atomic y ticket bloqueado por la vista."""
    vigente = ticket.asignaciones.filter(activo=True).first()
    if (vigente is not None and vigente.tecnico_id == tecnico.pk
            and vigente.scheduled_at == scheduled_at and ticket.scheduled_at == scheduled_at):
        return False
    ticket.asignaciones.filter(activo=True).update(activo=False)
    TicketAssignment.objects.create(
        ticket=ticket, tecnico=tecnico, asignado_por=autor, scheduled_at=scheduled_at,
    )
    ticket.scheduled_at = scheduled_at
    ticket.estado = 'asignada'
    ticket.save(update_fields=['scheduled_at', 'estado'])
    TicketEvent.objects.create(
        ticket=ticket, tipo_accion='reasignacion' if vigente else 'asignacion', usuario=autor,
        detalles=f'Asignado a {tecnico.get_full_name() or tecnico.username}',
    )
    return True
