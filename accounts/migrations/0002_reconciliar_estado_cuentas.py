"""AUD-005: reconciliación conservadora sin borrar campos ni reactivar cuentas.

Antes de adoptar is_active como fuente única, las bajas registradas en el campo
legado se trasladan a Django. Los demás usuarios y referencias no se modifican.
Revertir la migración no reactiva automáticamente cuentas desactivadas.
"""
from django.db import migrations


def conservar_desactivaciones(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.using(schema_editor.connection.alias).filter(
        activo_sistema=False, is_active=True,
    ).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [('accounts', '0001_initial')]
    operations = [migrations.RunPython(conservar_desactivaciones, migrations.RunPython.noop)]
