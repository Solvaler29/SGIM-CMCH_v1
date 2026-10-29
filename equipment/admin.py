from django.contrib import admin
from .models import Equipment


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'codigo_equipo', 'marca', 'modelo', 'numero_serie', 'ubicacion', 'estado_referencia')
    list_filter = ('estado_referencia', 'marca')
    search_fields = ('nombre', 'codigo_equipo', 'qr_identifier', 'numero_serie', 'marca', 'modelo')
    readonly_fields = ('creado_en', 'actualizado_en')