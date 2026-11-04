"""Reserva de códigos: el llamador debe guardar el ticket en la misma transacción."""
from datetime import timezone as utc_timezone

from django.db import connections
from django.utils import timezone


class LimiteCodigoTicket(Exception):
    pass


def reservar_codigo(using='default'):
    from .models import ContadorDiarioTicket, Ticket

    connection = connections[using]
    if not connection.in_atomic_block:
        raise RuntimeError('La reserva exige una transacción de creación.')
    fecha = timezone.now().astimezone(utc_timezone.utc).date()
    # ON CONFLICT espera al creador concurrente sin abortar la transacción.
    # La PK resuelve también el caso del primer ticket del día.
    tabla = connection.ops.quote_name(ContadorDiarioTicket._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO {tabla} (fecha, ultimo_correlativo) VALUES (%s, 0) '
            'ON CONFLICT (fecha) DO NOTHING', [fecha],
        )
    contador = ContadorDiarioTicket.objects.using(using).select_for_update().get(fecha=fecha)
    numero = contador.ultimo_correlativo + 1
    codigo = f'TIK-{fecha:%Y%m%d}-{numero:04d}'
    if len(codigo) > Ticket._meta.get_field('codigo_ticket').max_length:
        raise LimiteCodigoTicket('Se alcanzó el límite diario de códigos. Contacta al administrador.')
    contador.ultimo_correlativo = numero
    contador.save(using=using, update_fields=['ultimo_correlativo'])
    return codigo
