from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import Ticket, TicketEvent, TicketAssignment
from .forms import TicketForm
from core.models import Servicio, AreaProblema
from accounts.models import Area, User


@login_required
def lista_tickets(request):
    user = request.user
    if user.tiene_rol('administrador'):
        tickets = Ticket.objects.all()
    elif user.tiene_rol('supervisor'):
        tickets = Ticket.objects.filter(area_soporte__in=user.areas.all())
    elif user.tiene_rol('tecnico'):
        tickets = Ticket.objects.filter(asignaciones__tecnico=user, asignaciones__activo=True)
    else:
        tickets = Ticket.objects.filter(solicitante=user)
    tickets = tickets.order_by('-created_at')
    return render(request, 'tickets/lista_tickets.html', {'tickets': tickets})


@login_required
def registrar_ticket(request):
    if request.method == 'POST':
        form = TicketForm(request.POST, request.FILES, solicitante=request.user)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.solicitante = request.user
            ticket.save()
            form.save_m2m()
            TicketEvent.objects.create(
                ticket=ticket,
                tipo_accion='registro',
                usuario=request.user,
                detalles=f'Ticket registrado: {ticket.codigo_ticket}',
            )
            messages.success(request, f'Incidencia registrada correctamente: {ticket.codigo_ticket}')
            return redirect('tickets:detalle_ticket', pk=ticket.pk)
    else:
        form = TicketForm(solicitante=request.user)
    return render(request, 'tickets/registrar_ticket.html', {'form': form})


@login_required
def detalle_ticket(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)


@login_required
def redirigir_ticket(request, pk):
    if not request.user.tiene_rol('supervisor') and not request.user.tiene_rol('administrador'):
        messages.error(request, 'Solo el supervisor o administrador puede redirigir tickets.')
        return redirect('tickets:detalle_ticket', pk=pk)
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.method == 'POST':
        nueva_area_id = request.POST.get('area_soporte')
        nueva_area = get_object_or_404(Area, pk=nueva_area_id)
        area_anterior = ticket.area_soporte
        ticket.redirigido_de = ticket
        ticket.area_soporte = nueva_area
        ticket.estado = 'revision'
        ticket.save()
        TicketEvent.objects.create(
            ticket=ticket,
            tipo_accion='redireccion',
            usuario=request.user,
            detalles=f'Redirigido de {area_anterior} a {nueva_area}',
        )
        messages.success(request, f'Ticket redirigido a {nueva_area.nombre}.')
        return redirect('tickets:detalle_ticket', pk=pk)
    areas = Area.objects.filter(activa=True)
    return render(request, 'tickets/redirigir_ticket.html', {'ticket': ticket, 'areas': areas})


@login_required
def priorizar_ticket(request, pk):
    if not request.user.tiene_rol('supervisor') and not request.user.tiene_rol('administrador'):
        messages.error(request, 'Solo el supervisor puede cambiar la prioridad.')
        return redirect('tickets:detalle_ticket', pk=pk)
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.method == 'POST':
        prioridad = request.POST.get('prioridad')
        if prioridad in dict(Ticket.PRIORIDADES):
            anterior = ticket.prioridad
            ticket.prioridad = prioridad
            ticket.save()
            TicketEvent.objects.create(
                ticket=ticket,
                tipo_accion='cambio_prioridad',
                usuario=request.user,
                detalles=f'Prioridad cambiada de {anterior} a {prioridad}',
            )
            messages.success(request, f'Prioridad actualizada a {ticket.get_prioridad_display()}.')
        return redirect('tickets:detalle_ticket', pk=pk)
    return render(request, 'tickets/priorizar_ticket.html', {'ticket': ticket})


@login_required
def asignar_tecnico(request, pk):
    if not request.user.tiene_rol('supervisor') and not request.user.tiene_rol('administrador'):
        messages.error(request, 'Solo el supervisor puede asignar técnicos.')
        return redirect('tickets:detalle_ticket', pk=pk)
    ticket = get_object_or_404(Ticket, pk=pk)
    tecnicos = User.objects.filter(roles='tecnico', areas=ticket.area_soporte, activo_sistema=True)
    if request.method == 'POST':
        tecnico_id = request.POST.get('tecnico')
        tecnico = get_object_or_404(User, pk=tecnico_id)
        ticket.asignaciones.update(activo=False)
        TicketAssignment.objects.create(
            ticket=ticket,
            tecnico=tecnico,
            asignado_por=request.user,
        )
        ticket.estado = 'asignada'
        ticket.save()
        TicketEvent.objects.create(
            ticket=ticket,
            tipo_accion='asignacion',
            usuario=request.user,
            detalles=f'Asignado a {tecnico.get_full_name() or tecnico.username}',
        )
        messages.success(request, f'Técnico {tecnico.get_full_name() or tecnico.username} asignado.')
        return redirect('tickets:detalle_ticket', pk=pk)
    return render(request, 'tickets/asignar_tecnico.html', {
        'ticket': ticket, 'tecnicos': tecnicos
    })
    if not ticket.puede_ser_visto_por(request.user):
        messages.error(request, 'No tienes permiso para ver este ticket.')
        return redirect('tickets:lista_tickets')
    eventos = ticket.eventos.all()
    asignaciones = ticket.asignaciones.all().order_by('-fecha_asignacion')
    return render(request, 'tickets/detalle_ticket.html', {
        'ticket': ticket, 'eventos': eventos, 'asignaciones': asignaciones
    })