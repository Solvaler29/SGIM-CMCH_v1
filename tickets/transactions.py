"""Respuesta común para conflictos PostgreSQL recuperables de operaciones web."""
from functools import wraps

from django.db import OperationalError
from django.http import HttpResponse


def controlar_conflictos(vista):
    @wraps(vista)
    def ejecutar(*args, **kwargs):
        try:
            return vista(*args, **kwargs)
        except OperationalError as error:
            # Las vistas salen de atomic antes de llegar aquí. No esconder
            # desconexiones ni errores de programación como conflictos normales.
            if getattr(error.__cause__, 'pgcode', None) not in ('40001', '40P01', '55P03'):
                raise
            return HttpResponse(
                'No se guardaron cambios por un conflicto concurrente. '
                'Actualiza la página e inténtalo nuevamente.', status=409,
            )
    return ejecutar
