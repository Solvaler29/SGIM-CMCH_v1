from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Area


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'codigo', 'activa')
    list_filter = ('activa',)
    search_fields = ('nombre', 'codigo')


@admin.register(User)
class UserAdmin(UserAdmin):
    list_display = ('username', 'get_full_name', 'roles', 'correo_notificaciones', 'activo_sistema', 'is_staff')
    list_filter = ('roles', 'activo_sistema', 'is_staff', 'is_superuser', 'areas')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'correo_notificaciones')
    filter_horizontal = ('areas', 'groups', 'user_permissions')
    fieldsets = UserAdmin.fieldsets + (
        ('Roles y Áreas SGIM', {
            'fields': ('roles', 'areas', 'telefono', 'correo_notificaciones', 'activo_sistema'),
        }),
    )