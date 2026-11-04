"""Permisos de navegación calculados con la misma política del backend."""
from .permissions import puede_registrar_incidencia


def permisos_incidencias(request):
    return {'puede_registrar_incidencia': puede_registrar_incidencia(request.user)}
