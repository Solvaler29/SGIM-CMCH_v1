"""AUD-010: programación por asignación y vigente única, sin inventar historia."""
from django.db import migrations, models
from django.db.models import Count, F, OuterRef, Subquery


def conservar_programacion_actual(apps, schema_editor):
    Asignacion = apps.get_model('tickets', 'TicketAssignment')
    Ticket = apps.get_model('tickets', 'Ticket')
    alias = schema_editor.connection.alias
    asignaciones = Asignacion.objects.using(alias)
    duplicadas = list(asignaciones.filter(activo=True).values('ticket_id')
        .annotate(total=Count('pk')).filter(total__gt=1).order_by('ticket_id'))
    if duplicadas:
        raise RuntimeError(
            'AUD-010: migración detenida; asignaciones vigentes duplicadas '
            f'por ticket (sin seleccionar ni borrar registros): {duplicadas}'
        )
    # Con una sola vigente, la programación actual es atribuible a esa fila.
    # Las filas históricas permanecen nulas; los tickets sin vigente no se tocan.
    programacion = Ticket.objects.using(alias).filter(pk=OuterRef('ticket_id')).values('scheduled_at')[:1]
    asignaciones.filter(activo=True).update(scheduled_at=Subquery(programacion))


def verificar_reversion_segura(apps, schema_editor):
    Asignacion = apps.get_model('tickets', 'TicketAssignment')
    con_fecha = Asignacion.objects.using(schema_editor.connection.alias).filter(scheduled_at__isnull=False)
    perdida = con_fecha.exclude(activo=True, scheduled_at=F('ticket__scheduled_at'))
    if perdida.exists():
        raise RuntimeError(
            'AUD-010: reversión detenida para no perder programaciones históricas. '
            'Preservar y revisar los datos antes de aprobar una reversión destructiva.'
        )


class Migration(migrations.Migration):
    atomic = True
    dependencies = [('tickets', '0002_ticket_fotografia')]
    operations = [
        migrations.AddField(
            model_name='ticketassignment', name='scheduled_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Fecha y hora estimadas de atención'),
        ),
        migrations.RunPython(conservar_programacion_actual, verificar_reversion_segura),
        migrations.AddConstraint(
            model_name='ticketassignment',
            constraint=models.UniqueConstraint(
                fields=('ticket',), condition=models.Q(activo=True), name='uniq_ticket_asignacion_activa',
            ),
        ),
    ]
