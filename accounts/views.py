from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Q
from .models import User, Area
from .forms import CustomUserCreationForm, CustomAuthenticationForm, UserEditForm


def login_view(request):
    if request.user.is_authenticated:
        return redirect('core:dashboard')
    if request.method == 'POST':
        form = CustomAuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f'Bienvenido, {user.get_full_name() or user.username}.')
            return redirect('core:dashboard')
    else:
        form = CustomAuthenticationForm()
    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'Has cerrado sesión correctamente.')
    return redirect('accounts:login')


def registro_view(request):
    """Registro de nuevos usuarios (solo administrador puede crear cuentas)."""
    if not request.user.is_authenticated or not request.user.tiene_rol('administrador'):
        messages.error(request, 'Solo el administrador puede crear cuentas de usuario.')
        return redirect('core:dashboard')
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'Usuario {user.username} creado correctamente.')
            return redirect('accounts:usuarios_list')
    else:
        form = CustomUserCreationForm()
    return render(request, 'accounts/registro.html', {'form': form})


@login_required
def perfil_view(request):
    return render(request, 'accounts/perfil.html', {'usuario': request.user})


@login_required
@user_passes_test(lambda u: u.tiene_rol('administrador'))
def usuarios_list(request):
    usuarios = User.objects.all().order_by('username')
    return render(request, 'accounts/usuarios_list.html', {'usuarios': usuarios})


@login_required
@user_passes_test(lambda u: u.tiene_rol('administrador'))
def usuario_editar(request, pk):
    usuario = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=usuario)
        if form.is_valid():
            form.save()
            messages.success(request, f'Usuario {usuario.username} actualizado.')
            return redirect('accounts:usuarios_list')
    else:
        form = UserEditForm(instance=usuario)
    return render(request, 'accounts/usuario_editar.html', {'form': form, 'usuario': usuario})