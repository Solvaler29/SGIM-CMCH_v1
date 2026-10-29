"""
Modelos de tickets e incidencias del SGIM-CMCH.

Define el ciclo de vida completo de una incidencia:
registro, revisión, planificación, asignación, atención, validación y cierre.
Incluye entidad de atención para conservar múltiples intervenciones y un historial
de auditoría de todas las acciones importantes.
"""
from django.db import models
from django.conf import settings
from core.models import Servicio, AreaProblema
from accounts.models import Area
from equipment.models import Equipment


class Ticket(models.Model):
    """
    Ticket de incidencia. Conserva su identificador aunque sea redirigido a otra área.
    """
    ESTADOS = [
        ('registrada', 'Registrada'),
        ('revision', 'En revisión / Pendiente de planificación'),
        ('asignada', 'Asignada'),
        ('en_atencion', 'En atención'),
        ('pendiente_validacion', 'Pendiente de validación del supervisor'),
        ('devuelta', 'Devuelta para corrección'),
        ('cerrada_tecnicamente', 'Cerrada técnicamente'),
    ]

    PRIORIDADES = [
        ('baja', 'Baja'),
        ('media', 'Media'),
        ('alta', 'Alta'),
        ('critica', 'Crítica'),
    ]

    codigo_ticket = models.CharField(max_length=20, unique=True, editable=False)
    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='tickets_solicitados',
        verbose_name='Usuario que reporta',
    )
    servicio = models.ForeignKey(
        Servicio,
        on_delete=models.PROTECT,
        related_name='tickets',
        verbose_name='Servicio UPS correspondiente',
    )
    area_problema = models.ForeignKey(
        AreaProblema,
        on_delete=models.PROTECT,
        related_name='tickets',
        verbose_name='Área donde ocurre el problema',
    )
    area_soporte = models.ForeignKey(
        Area,
        on_delete=models.PROTECT,
        related_name='tickets_area',
        verbose_name='Área de soporte de destino',
    )
    descripcion = models.TextField(verbose_name='Descripción detallada de la incidencia')
    acciones_previas = models.TextField(blank=True, verbose_name='Acciones previas realizadas')
    equipo = models.ForeignKey(
        Equipment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets',
        verbose_name='Equipo relacionado (identificado por QR)',
    )
    estado = models.CharField(max_length=30, choices=ESTADOS, default='registrada')
    prioridad = models.CharField(max_length=10, choices=PRIORIDADES, default='media')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha y hora de registro')
    scheduled_at = models.DateTimeField(null=True, blank=True, verbose_name='Fecha y hora estimadas de atención')
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name='Fecha y hora de cierre técnico aprobado')

    codigo_ticket_original = models.CharField(max_length=20, blank=True, help_text='Conserva el código aunque sea redirigido')
    redirigido_de = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='redirecciones',
        verbose_name='Redirigido desde el ticket',
    )

    class Meta:
        verbose_name = 'Ticket'
        verbose_name_plural = 'Tickets'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['codigo_ticket']),
            models.Index(fields=['estado', 'area_soporte']),
            models.Index(fields=['solicitante']),
            models.Index(fields=['created_at']),
        ]



class TicketEvent(models.Model):
    """
    Historial de auditoría de acciones importantes sobre un ticket.
    Los usuarios normales no pueden modificar ni eliminar estos eventos.
    """
    TIPO_ACCION = [
        ('registro', 'Registro de incidencia'),
        ('cambio_prioridad', 'Cambio de prioridad'),
        ('asignacion', 'Asignación de técnico'),
        ('reasignacion', 'Reasignación de técnico'),
        ('redireccion', 'Redirección entre áreas'),
        ('cambio_estado', 'Cambio de estado'),
        ('inicio_atencion', 'Inicio real de atención'),
        ('fin_atencion', 'Finalización de atención'),
        ('materiales_registrados', 'Materiales y acciones registrados'),
        ('aprobacion', 'Aprobación del supervisor'),
        ('devolucion', 'Devolución para corrección'),
        ('cierre', 'Cierre técnico'),
        ('reapertura', 'Reapertura de ticket'),
        ('encuesta', 'Encuesta de satisfacción'),
    ]

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='eventos')
    tipo_accion = models.CharField(max_length=30, choices=TIPO_ACCION)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='eventos_creados',
    )
    fecha_hora = models.DateTimeField(auto_now_add=True)
    detalles = models.TextField(blank=True, help_text='Detalles pertinentes de la acción')

    class Meta:
        verbose_name = 'Evento de Historial'
        verbose_name_plural = 'Eventos de Historial'
        ordering = ['-fecha_hora']

    def __str__(self):
        return f'{self.ticket.codigo_ticket} - {self.get_tipo_accion_display()} - {self.fecha_hora}'


class TicketAssignment(models.Model):
    """
    Asignación de un técnico a un ticket. Conserva asignaciones previas en el historial.
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='asignaciones')
    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='asignaciones_tecnico',
        limit_choices_to={'roles': 'tecnico'},
    )
    asignado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='asignaciones_hechas',
    )
    fecha_asignacion = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True, help_text='Indica si es la asignación vigente')

    class Meta:
        verbose_name = 'Asignación'
        verbose_name_plural = 'Asignaciones'
        ordering = ['-fecha_asignacion']

    def __str__(self):
        return f'{self.ticket.codigo_ticket} -> {self.tecnico} ({self.fecha_asignacion})'


class Satisfaccion(models.Model):
    """
    Encuesta de satisfacción independiente del cierre técnico.
    """
    ticket = models.OneToOneField(Ticket, on_delete=models.CASCADE, related_name='encuesta')
    puntuacion = models.IntegerField(help_text='Escala numérica configurable (1-5)')
    comentarios = models.TextField(blank=True)
    fecha_respuesta = models.DateTimeField(auto_now_add=True)
    respondido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='encuestas_respondidas',
    )

    class Meta:
        verbose_name = 'Encuesta de Satisfacción'
        verbose_name_plural = 'Encuestas de Satisfacción'

    def __str__(self):
        return f'Encuesta {self.ticket.codigo_ticket} - {self.puntuacion}'
    def __str__(self):
        return f'{self.codigo_ticket} - {self.estado}'

    def save(self, *args, **kwargs):
        if not self.codigo_ticket:
            from django.utils import timezone
            hoy = timezone.now().strftime('%Y%m%d')
            ultimo = Ticket.objects.filter(
                codigo_ticket__startswith=f'TIK-{hoy}-'
            ).order_by('-codigo_ticket').first()
            if ultimo:
                try:
                    num = int(ultimo.codigo_ticket.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    num = 1
            else:
                num = 1
            self.codigo_ticket = f'TIK-{hoy}-{num:04d}'
        super().save(*args, **kwargs)

    def puede_ser_visto_por(self, usuario):
        return usuario.puede_ver_ticket(self)