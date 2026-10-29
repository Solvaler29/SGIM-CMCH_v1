"""
Modelo de equipos simulados para consulta por QR.

Esta tabla es independiente de los tickets y sirve únicamente para identificar
un equipo mediante su código QR y recuperar sus datos básicos simulados.
"""
from django.db import models


class Equipment(models.Model):
    """
    Equipo simulado del catálogo QR.

    Todos los registros son ficticios. No representan equipos reales de la clínica.
    """
    nombre = models.CharField(max_length=150, help_text='Nombre o tipo del equipo')
    codigo_equipo = models.CharField(max_length=50, unique=True, help_text='Código único de equipo')
    qr_identifier = models.CharField(max_length=100, unique=True, help_text='Identificador o contenido esperado del QR')
    marca = models.CharField(max_length=100)
    modelo = models.CharField(max_length=100)
    numero_serie = models.CharField(max_length=100, blank=True)
    ubicacion = models.CharField(max_length=150, blank=True, help_text='Ubicación de referencia (demo)')
    estado_referencia = models.CharField(
        max_length=50,
        blank=True,
        help_text='Estado de referencia (ej. Operativo, En reparación, Fuera de servicio)',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Equipo (simulado)'
        verbose_name_plural = 'Equipos (simulados)'
        ordering = ['nombre']

    def __str__(self):
        return f'{self.nombre} - {self.codigo_equipo}'

    @property
    def datos_basicos(self):
        """Devuelve los datos básicos del equipo para la respuesta QR."""
        return {
            'nombre': self.nombre,
            'codigo_equipo': self.codigo_equipo,
            'marca': self.marca,
            'modelo': self.modelo,
            'numero_serie': self.numero_serie,
            'ubicacion': self.ubicacion,
            'estado_referencia': self.estado_referencia,
        }