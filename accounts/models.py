"""
Modelos de cuentas y roles del sistema SGIM-CMCH.

Define un modelo de usuario personalizado con roles y áreas de soporte.
Cada persona tiene una cuenta individual. Un usuario puede tener varios roles
y pertenecer a varias áreas, pero nunca comparte cuenta con otra persona.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Area(models.Model):
    """Área de soporte del sistema (TI, Ingeniería Clínica, Mantenimiento)."""
    nombre = models.CharField(max_length=100, unique=True)
    codigo = models.CharField(max_length=20, unique=True, help_text='Código corto del área, ej. TI, IC, MAN')
    activa = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Área'
        verbose_name_plural = 'Áreas'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class User(AbstractUser):
    """
    Usuario personalizado del SGIM-CMCH.

    Roles:
      - solicitante: puede registrar incidencias y consultar sus propios tickets
      - supervisor: revisa, prioriza, programa y asigna tickets de su área; aprueba cierres
      - tecnico: atiende tickets asignados, registra diagnósticos y finaliza intervenciones
      - administrador: gestiona usuarios, áreas y configuración del sistema
    """
    ROLES = [
        ('solicitante', 'Solicitante'),
        ('supervisor', 'Supervisor / Planificador'),
        ('tecnico', 'Técnico de Soporte'),
        ('administrador', 'Administrador Técnico'),
    ]

    roles = models.CharField(max_length=20, choices=ROLES, default='solicitante')
    areas = models.ManyToManyField(
        Area,
        related_name='usuarios',
        blank=True,
        help_text='Áreas a las que pertenece este usuario.',
    )
    telefono = models.CharField(max_length=20, blank=True)
    correo_notificaciones = models.EmailField(blank=True)
    activo_sistema = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'

    def __str__(self):
        return f'{self.get_full_name() or self.username} ({self.get_roles_display()})'

    def get_roles_display(self):
        return dict(self.ROLES).get(self.roles, self.roles)

    def tiene_rol(self, rol):
        return self.roles == rol

    def pertenece_area(self, area):
        if isinstance(area, Area):
            return self.areas.filter(pk=area.pk).exists()
        return self.areas.filter(nombre=area).exists()

    def puede_gestionar_area(self, area):
        """Un supervisor puede gestionar solo las áreas que tiene asignadas."""
        if self.tiene_rol('administrador'):
            return True
        if self.tiene_rol('supervisor'):
            return self.pertenece_area(area)
        return False

    def puede_ver_ticket(self, ticket):
        """Restricción de acceso por área y asignación."""
        if self.tiene_rol('administrador'):
            return True
        if self.tiene_rol('solicitante'):
            return ticket.solicitante_id == self.pk
        if self.tiene_rol('supervisor'):
            return ticket.area_soporte_id in list(self.areas.values_list('pk', flat=True))
        if self.tiene_rol('tecnico'):
            return ticket.asignaciones.filter(tecnico_id=self.pk, activo=True).exists()
        return False