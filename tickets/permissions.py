"""Política de acceso a tickets por acción, rol operativo y área actual."""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.http import Http404


CONSULTAR = 'consultar'
VER_EVIDENCIA = 'ver_evidencia'
CLASIFICAR = 'clasificar'
REDIRIGIR = 'redirigir'
ASIGNAR_TECNICO = 'asignar_tecnico'
REVISAR_ATENCION = 'revisar_atencion'
INICIAR_ATENCION = 'iniciar_atencion'
EDITAR_ATENCION = 'editar_atencion'
FINALIZAR_ATENCION = 'finalizar_atencion'
ESTADOS_ACCION_TECNICA = {
    INICIAR_ATENCION: ('asignada',),
    EDITAR_ATENCION: ('en_atencion',),
    FINALIZAR_ATENCION: ('en_atencion',),
}
ACCIONES_GESTION = frozenset({
    CLASIFICAR, REDIRIGIR, ASIGNAR_TECNICO, REVISAR_ATENCION,
})
ROLES_OPERATIVOS = frozenset({
    'solicitante', 'supervisor', 'tecnico', 'administrador',
})


def puede_registrar_incidencia(usuario):
    """Regla provisional MVP-01, pendiente de validación institucional.

    El rol operativo solicitante es obligatorio; staff y superusuario no
    conceden excepciones a este permiso.
    """
    return (usuario.is_authenticated and usuario.is_active
            and usuario.tiene_rol('solicitante'))


def tiene_acceso_global(usuario):
    """Excepción explícita: solo el rol operativo administrador es global."""
    return usuario.is_authenticated and usuario.is_active and usuario.tiene_rol('administrador')


def puede_gestionar_area(usuario, area):
    if not usuario.is_authenticated or not usuario.is_active:
        return False
    if tiene_acceso_global(usuario):
        return True
    return usuario.tiene_rol('supervisor') and usuario.pertenece_area(area)


def tickets_para_usuario(usuario, accion=CONSULTAR, queryset=None):
    """Devuelve solo objetos autorizados, sin ampliar permisos por ser su dueño.

    La propiedad del ticket permite consulta, nunca gestión de un área ajena.
    Las acciones desconocidas y los roles no reconocidos se deniegan.
    """
    from .models import Ticket

    if queryset is None:
        queryset = Ticket.objects.all()
    if (accion not in ACCIONES_GESTION and accion not in ESTADOS_ACCION_TECNICA
            and accion not in (CONSULTAR, VER_EVIDENCIA)):
        return queryset.none()
    if (not usuario.is_authenticated or not usuario.is_active
            or usuario.roles not in ROLES_OPERATIVOS):
        return queryset.none()
    if accion == ASIGNAR_TECNICO:
        queryset = queryset.filter(
            closed_at__isnull=True,
            estado__in=[valor for valor, _ in Ticket.ESTADOS if valor != 'cerrada_tecnicamente'],
        )
    # La excepción administrativa no habilita operaciones propias del técnico.
    if accion in ESTADOS_ACCION_TECNICA:
        if not usuario.tiene_rol('tecnico'):
            return queryset.none()
        return queryset.filter(
            asignaciones__tecnico_id=usuario.pk, asignaciones__activo=True,
            estado__in=ESTADOS_ACCION_TECNICA[accion], closed_at__isnull=True,
        ).distinct()
    if tiene_acceso_global(usuario):
        return queryset

    areas = usuario.areas.values_list('pk', flat=True)
    if accion in ACCIONES_GESTION:
        if usuario.tiene_rol('supervisor'):
            return queryset.filter(area_soporte_id__in=areas)
        return queryset.none()

    alcance = Q(solicitante_id=usuario.pk)
    if usuario.tiene_rol('supervisor'):
        alcance |= Q(area_soporte_id__in=areas)
    elif usuario.tiene_rol('tecnico'):
        alcance |= Q(asignaciones__tecnico_id=usuario.pk, asignaciones__activo=True)
    return queryset.filter(alcance).distinct()


def puede_operar_ticket(usuario, ticket, accion=CONSULTAR):
    if ticket.pk is None:
        return False
    if accion in ESTADOS_ACCION_TECNICA:
        try:
            obtener_contexto_atencion_autorizado(usuario, ticket.pk, accion)
        except Http404:
            return False
        return True
    return tickets_para_usuario(usuario, accion).filter(pk=ticket.pk).exists()


def obtener_ticket_autorizado(usuario, pk, accion=CONSULTAR, queryset=None):
    """Un objeto ajeno y uno inexistente generan la misma respuesta 404."""
    return get_object_or_404(tickets_para_usuario(usuario, accion, queryset=queryset), pk=pk)


def obtener_contexto_atencion_autorizado(usuario, ticket_pk, accion, bloquear=False):
    """Autoriza ticket e intervención sin crear ni modificar registros.

    Las rutas actuales identifican ticket, no intervención. Si varias atenciones
    propias resultan ambiguas, se deniega hasta resolver AUD-006.
    """
    if accion not in ESTADOS_ACCION_TECNICA:
        raise Http404
    ticket = obtener_ticket_autorizado(usuario, ticket_pk, accion)
    if bloquear:
        from .models import Ticket
        # Evitar FOR UPDATE sobre el DISTINCT de la consulta técnica. Todos los
        # escritores del trabajo bloquean primero el ticket, igual que AUD-010.
        Ticket.objects.select_for_update().get(pk=ticket.pk)
        ticket = obtener_ticket_autorizado(usuario, ticket_pk, accion)
    atenciones = list(ticket.atenciones.filter(tecnico_id=usuario.pk)[:2])
    if len(atenciones) > 1:
        raise Http404
    atencion = atenciones[0] if atenciones else None
    if atencion is None:
        if accion == INICIAR_ATENCION:
            return ticket, None
        raise Http404
    if (atencion.finalizado_por_tecnico or atencion.enviado_a_revision
            or atencion.work_finished_at is not None):
        raise Http404
    if accion != INICIAR_ATENCION and atencion.work_started_at is None:
        raise Http404
    return ticket, atencion
