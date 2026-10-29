"""
Modelos de atenciones técnicas del SGIM-CMCH.

Permite conservar múltiples intervenciones por ticket, cada una con sus propios
tiempos y resultados, sin sobrescribir intervenciones anteriores.
"""
from django.db import models
from django.conf import settings
from tickets.models import Ticket


class AtencionTecnica(models.Model):
    """
    Atención técnica realizada sobre un ticket.
    Cada atención conserva sus propios tiempos y resultados.
    """
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='atenciones',
        verbose_name='Ticket',
    )
    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='atenciones_tecnico',
        limit_choices_to={'roles': 'tecnico'},
        verbose_name='Técnico',
    )

    # Tiempos de la intervención
    work_started_at = models.DateTimeField(null=True, blank=True, verbose_name='Inicio real del trabajo')
    work_finished_at = models.DateTimeField(null=True, blank=True, verbose_name='Finalización declarada')

    # Contenido de la intervención
    diagnostico = models.TextField(blank=True, verbose_name='Diagnóstico')
    acciones_realizadas = models.TextField(blank=True, verbose_name='Acciones realizadas')
    observaciones = models.TextField(blank=True, verbose_name='Observaciones')
    materiales_requeridos = models.TextField(blank=True, verbose_name='Materiales y repuestos necesarios')
    recursos_utilizados = models.TextField(blank=True, verbose_name='Recursos utilizados o pendientes')
    evidencias = models.TextField(blank=True, help_text='Rutas o referencias de evidencias adicionales')

    # Estado de la intervención
    finalizado_por_tecnico = models.BooleanField(default=False, verbose_name='Técnico declara terminado')
    enviado_a_revision = models.BooleanField(default=False, verbose_name='Enviado a revisión del supervisor')

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Atención Técnica'
        verbose_name_plural = 'Atenciones Técnicas'
        ordering = ['-creado_en']

    def __str__(self):
        return f'Atención {self.pk} - {self.ticket.codigo_ticket} - {self.tecnico}'


class RevisionSupervisor(models.Model):
    """
    Revisión del supervisor sobre una atención técnica.
    Puede aprobar o devolver con justificación.
    """
    DECISIONES = [
        ('aprobado', 'Aprobado y cerrado técnicamente'),
        ('devuelto', 'Devuelto para corrección'),
    ]

    atencion = models.ForeignKey(
        AtencionTecnica,
        on_delete=models.CASCADE,
        related_name='revisiones',
        verbose_name='Atención técnica',
    )
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='revisiones_supervisor',
        limit_choices_to={'roles__in': ['supervisor', 'administrador']},
        verbose_name='Supervisor',
    )
    decision = models.CharField(max_length=20, choices=DECISIONES, verbose_name='Decisión')
    justificacion = models.TextField(blank=True, verbose_name='Justificación de la decisión')
    fecha_decision = models.DateTimeField(auto_now_add=True, verbose_name='Fecha y hora de la decisión')

    class Meta:
        verbose_name = 'Revisión de Supervisor'
        verbose_name_plural = 'Revisiones de Supervisor'
        ordering = ['-fecha_decision']

    def __str__(self):
        return f'Revisión {self.pk} - {self.get_decision_display()} - {self.supervisor}'