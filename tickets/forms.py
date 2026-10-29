from django import forms
from django.core.exceptions import ValidationError
from .models import Ticket
from core.models import Servicio, AreaProblema
from accounts.models import Area
from equipment.models import Equipment


class TicketForm(forms.ModelForm):
    """Formulario de registro de incidencia con validación de fotografía obligatoria."""

    class Meta:
        model = Ticket
        fields = [
            'servicio', 'area_problema', 'area_soporte',
            'descripcion', 'acciones_previas', 'equipo', 'fotografia',
        ]
        widgets = {
            'servicio': forms.Select(attrs={'class': 'form-select'}),
            'area_problema': forms.Select(attrs={'class': 'form-select'}),
            'area_soporte': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'acciones_previas': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'equipo': forms.Select(attrs={'class': 'form-select'}),
        }

    fotografia = forms.ImageField(
        required=True,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        help_text='Adjunta al menos una fotografía del problema.',
    )

    def __init__(self, *args, solicitante=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['servicio'].queryset = Servicio.objects.filter(activo=True)
        self.fields['area_problema'].queryset = AreaProblema.objects.filter(activo=True)
        self.fields['area_soporte'].queryset = Area.objects.filter(activa=True)
        self.fields['equipo'].queryset = Equipment.objects.all()
        self.fields['equipo'].required = False
        self.fields['equipo'].empty_label = 'Seleccionar equipo (opcional, identificar por QR)'

    def clean_fotografia(self):
        foto = self.cleaned_data.get('fotografia')
        if not foto:
            raise ValidationError('La fotografía es obligatoria.')
        # Validar tamaño (máximo 5 MB)
        if foto.size > 5 * 1024 * 1024:
            raise ValidationError('La fotografía no debe superar los 5 MB.')
        # Validar extensión
        ext = foto.name.lower().split('.')[-1] if '.' in foto.name else ''
        if ext not in ('jpg', 'jpeg', 'png', 'webp'):
            raise ValidationError('Solo se permiten imágenes JPG, JPEG, PNG o WEBP.')
        return foto