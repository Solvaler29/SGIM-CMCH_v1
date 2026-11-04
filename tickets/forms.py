from django import forms
from django.core.exceptions import ValidationError
from .models import Ticket
from core.models import Servicio, AreaProblema
from accounts.models import Area, User
from equipment.models import Equipment


class TicketAssignmentForm(forms.Form):
    tecnico = forms.ModelChoiceField(
        queryset=User.objects.none(), label='Técnico responsable',
        empty_label='Selecciona un técnico',
        widget=forms.Select(attrs={'class': 'form-select form-select-cmch'}),
    )
    scheduled_at = forms.DateTimeField(
        required=False, label='Fecha y hora estimadas (opcional)',
        widget=forms.DateTimeInput(
            format='%Y-%m-%dT%H:%M',
            attrs={'type': 'datetime-local', 'class': 'form-control form-control-cmch'},
        ),
    )

    def __init__(self, *args, ticket, **kwargs):
        super().__init__(*args, **kwargs)
        # El mismo conjunto se usa para mostrar y validar la selección en POST.
        self.fields['tecnico'].queryset = User.objects.filter(
            roles='tecnico', areas=ticket.area_soporte, is_active=True,
        )


class TicketForm(forms.ModelForm):
    """Formulario de registro de incidencia con validación de fotografía obligatoria."""

    class Meta:
        model = Ticket
        fields = [
            'servicio', 'area_problema', 'area_soporte',
            'descripcion', 'acciones_previas', 'equipo', 'fotografia',
        ]
        widgets = {
            'servicio': forms.Select(attrs={'class': 'form-select form-select-cmch'}),
            'area_problema': forms.Select(attrs={'class': 'form-select form-select-cmch'}),
            'area_soporte': forms.Select(attrs={'class': 'form-select form-select-cmch'}),
            'descripcion': forms.Textarea(attrs={
                'class': 'form-control form-control-cmch',
                'rows': 4,
            }),
            'acciones_previas': forms.Textarea(attrs={
                'class': 'form-control form-control-cmch',
                'rows': 2,
            }),
            'equipo': forms.Select(attrs={'class': 'form-select form-select-cmch', 'id': 'id_equipo'}),
        }

    fotografia = forms.ImageField(
        required=True,
        error_messages={'required': 'Adjunta una fotografía del problema.',
                        'invalid_image': 'El archivo no es una imagen válida o está dañado.'},
        widget=forms.ClearableFileInput(attrs={'class': 'form-control form-control-cmch', 'accept': 'image/*'}),
        help_text='Adjunta al menos una fotografía del problema.',
    )

    def __init__(self, *args, solicitante=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['servicio'].queryset = Servicio.objects.filter(activo=True)
        self.fields['servicio'].empty_label = 'Selecciona un servicio'
        self.fields['area_problema'].queryset = AreaProblema.objects.filter(activo=True)
        self.fields['area_problema'].empty_label = 'Selecciona un tipo'
        self.fields['area_soporte'].queryset = Area.objects.filter(activa=True)
        self.fields['area_soporte'].empty_label = 'Selecciona un área'
        self.fields['equipo'].queryset = Equipment.objects.all()
        self.fields['equipo'].required = False
        self.fields['equipo'].empty_label = 'Sin equipo asociado'
        for nombre, campo in self.fields.items():
            campo.widget.attrs['aria-describedby'] = f'error_{nombre}'
            if self.is_bound and nombre in self.errors:
                campo.widget.attrs['aria-invalid'] = 'true'

    def clean(self):
        cleaned = super().clean()
        if 'codigo_ticket' in self.data:
            raise ValidationError('El código del ticket se genera automáticamente.')
        return cleaned

    def clean_fotografia(self):
        foto = self.cleaned_data.get('fotografia')
        if not foto:
            raise ValidationError('La fotografía es obligatoria.')
        # Validar tamaño (máximo 5 MB)
        if foto.size > 5 * 1024 * 1024:
            raise ValidationError('La fotografía no debe superar los 5 MB.')
        # Validar extensión
        ext = foto.name.lower().split('.')[-1] if '.' in foto.name else ''
        if ext not in ('jpg', 'jpeg', 'png', 'webp', 'gif'):
            raise ValidationError('Solo se permiten imágenes JPG, JPEG, PNG, WEBP o GIF.')
        formatos = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP', 'gif': 'GIF'}
        if getattr(foto.image, 'format', None) != formatos[ext]:
            raise ValidationError('El contenido de la fotografía no coincide con su formato. Usa JPG, PNG, WEBP o GIF.')
        return foto
