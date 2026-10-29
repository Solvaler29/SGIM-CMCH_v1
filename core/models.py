"""
Modelos core del SGIM-CMCH: Áreas y Servicios.

Define los servicios (UPS) y las áreas donde ocurren los problemas.
"""
from django.db import models
from accounts.models import Area


class Servicio(models.Model):
    """
    Servicio correspondiente a una incidencia (ej. UPS, red eléctrica, climatización, etc.).
    """
    nombre = models.CharField(max_length=100, unique=True)
    codigo = models.CharField(max_length=20, unique=True, help_text='Código corto del servicio')
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Servicio'
        verbose_name_plural = 'Servicios'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class AreaProblema(models.Model):
    """
    Área física o funcional donde ocurre el problema (distinta del área de soporte destino).
    """
    nombre = models.CharField(max_length=100, unique=True)
    codigo = models.CharField(max_length=20, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Área de Problema'
        verbose_name_plural = 'Áreas de Problema'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre