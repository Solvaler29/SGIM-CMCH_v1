from django import template

register = template.Library()


@register.filter
def estado_badge(estado):
    """Devuelve la clase de color de Bootstrap para el estado del ticket."""
    mapping = {
        'registrada': 'secondary',
        'revision': 'warning',
        'asignada': 'info',
        'en_atencion': 'primary',
        'pendiente_validacion': 'warning',
        'devuelta': 'danger',
        'cerrada_tecnicamente': 'success',
    }
    return mapping.get(estado, 'secondary')


@register.filter
def prioridad_badge(prioridad):
    """Devuelve la clase de color de Bootstrap para la prioridad."""
    mapping = {
        'baja': 'success',
        'media': 'warning',
        'alta': 'danger',
        'critica': 'dark',
    }
    return mapping.get(prioridad, 'secondary')


@register.filter
def estado_equipo_badge(estado):
    """Devuelve la clase de color de Bootstrap para el estado del equipo."""
    mapping = {
        'Operativo': 'success',
        'En reparación': 'warning',
        'Fuera de servicio': 'danger',
    }
    return mapping.get(estado, 'secondary')