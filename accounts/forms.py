from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import User, Area


class CustomAuthenticationForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Usuario'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Contraseña'}))


class CustomUserCreationForm(UserCreationForm):
    roles = forms.ChoiceField(choices=User.ROLES, widget=forms.Select(attrs={'class': 'form-select'}))
    areas = forms.ModelMultipleChoiceField(
        queryset=Area.objects.filter(activa=True),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select'}),
    )
    first_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    correo_notificaciones = forms.EmailField(required=False, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    telefono = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'roles', 'areas',
                  'telefono', 'correo_notificaciones', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ('password1', 'password2'):
            self.fields[field_name].widget.attrs.update({'class': 'form-control'})


class UserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'roles', 'areas',
                  'telefono', 'correo_notificaciones', 'activo_sistema', 'is_staff')
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'roles': forms.Select(attrs={'class': 'form-select'}),
            'areas': forms.SelectMultiple(attrs={'class': 'form-select'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'correo_notificaciones': forms.EmailInput(attrs={'class': 'form-control'}),
            'activo_sistema': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }