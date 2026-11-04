"""AUD-005: estado canónico, sesiones existentes e integridad histórica."""
from tempfile import TemporaryDirectory
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import authenticate
from django.core.files.base import ContentFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import Servicio, AreaProblema
from maintenance.models import AtencionTecnica, RevisionSupervisor
from tickets.models import Ticket, TicketAssignment, TicketEvent
from tickets.permissions import (
    CONSULTAR, VER_EVIDENCIA, ACCIONES_GESTION, ESTADOS_ACCION_TECNICA,
    puede_operar_ticket, tiene_acceso_global,
)
from .forms import UserEditForm
from .models import User, Area


class DesactivacionEfectivaTests(TestCase):
    clave = 'Prueba-local-AUD005!'

    @classmethod
    def setUpTestData(cls):
        cls.area = Area.objects.create(nombre='TI ficticia', codigo='TI')
        cls.admin = User.objects.create_user(username='admin', password=cls.clave,
            roles='administrador', is_staff=True, is_superuser=True)
        cls.tecnico = User.objects.create_user(username='tecnico', password=cls.clave, roles='tecnico')
        cls.supervisor = User.objects.create_user(username='supervisor', password=cls.clave, roles='supervisor')
        cls.solicitante = User.objects.create_user(username='solicitante', password=cls.clave, roles='solicitante')
        cls.tecnico.areas.add(cls.area)
        cls.supervisor.areas.add(cls.area)
        servicio = Servicio.objects.create(nombre='Servicio ficticio', codigo='TEST')
        sala = AreaProblema.objects.create(nombre='Sala ficticia', codigo='SALA')
        cls.ticket = Ticket.objects.create(codigo_ticket='AUD005-TEST',
            solicitante=cls.solicitante, servicio=servicio, area_problema=sala,
            area_soporte=cls.area, descripcion='Prueba de cuenta', estado='en_atencion')
        TicketAssignment.objects.create(ticket=cls.ticket, tecnico=cls.tecnico, asignado_por=cls.admin)
        AtencionTecnica.objects.create(ticket=cls.ticket, tecnico=cls.tecnico,
                                      work_started_at=timezone.now(), diagnostico='Registro histórico')
        TicketEvent.objects.create(ticket=cls.ticket, usuario=cls.tecnico,
                                   tipo_accion='inicio_atencion', detalles='Evento ficticio')

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.administrador = Client(enforce_csrf_checks=True)
        self.administrador.force_login(self.admin)
        self.administrador.get(reverse('core:dashboard'))
        temporal = TemporaryDirectory(prefix='sgim-aud005-')
        self.addCleanup(temporal.cleanup)
        configuracion = override_settings(MEDIA_ROOT=temporal.name)
        configuracion.enable()
        self.addCleanup(configuracion.disable)
        self.ticket.fotografia.save('ficticia.png', ContentFile(b'Archivo ficticio AUD005'), save=True)

    def cambiar_estado(self, usuario, activo):
        datos = {
            'first_name': usuario.first_name, 'last_name': usuario.last_name,
            'email': usuario.email, 'roles': usuario.roles,
            'areas': list(usuario.areas.values_list('pk', flat=True)),
            'telefono': usuario.telefono, 'correo_notificaciones': usuario.correo_notificaciones,
        }
        if activo:
            datos['is_active'] = 'on'
        if usuario.is_staff:
            datos['is_staff'] = 'on'
        response = self.administrador.post(reverse('accounts:usuario_editar', args=[usuario.pk]),
            datos, HTTP_X_CSRFTOKEN=self.administrador.cookies[settings.CSRF_COOKIE_NAME].value)
        self.assertEqual(response.status_code, 302)
        usuario.refresh_from_db()
        self.assertEqual(usuario.is_active, activo)

    def snapshot(self):
        return [list(model.objects.order_by('pk').values()) for model in (
            Ticket, TicketAssignment, AtencionTecnica, TicketEvent, RevisionSupervisor,
        )]

    def sesion_previa(self, usuario):
        self.client.force_login(usuario)
        self.client.get(reverse('core:dashboard'))
        return self.client.cookies[settings.CSRF_COOKIE_NAME].value

    def test_usuario_activo_inicia_sesion_por_formulario_con_csrf(self):
        self.client.get(reverse('accounts:login'))
        response = self.client.post(reverse('accounts:login'), {
            'username': self.tecnico.username, 'password': self.clave,
        }, HTTP_X_CSRFTOKEN=self.client.cookies[settings.CSRF_COOKIE_NAME].value)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(self.tecnico.pk))

    def test_administrador_desactiva_sin_borrar_identidad_ni_historial(self):
        antes = self.snapshot()
        cantidad = User.objects.count()
        self.cambiar_estado(self.tecnico, False)
        self.assertEqual(User.objects.count(), cantidad)
        self.assertEqual(self.snapshot(), antes)
        self.assertTrue(self.ticket.asignaciones.get(tecnico=self.tecnico).activo)

    def test_inactivo_no_autentica_y_muestra_error_generico(self):
        self.cambiar_estado(self.tecnico, False)
        self.assertIsNone(authenticate(username=self.tecnico.username, password=self.clave))
        self.client.get(reverse('accounts:login'))
        response = self.client.post(reverse('accounts:login'), {
            'username': self.tecnico.username, 'password': self.clave,
        }, HTTP_X_CSRFTOKEN=self.client.cookies[settings.CSRF_COOKIE_NAME].value)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        errores = list(response.context['form'].non_field_errors())
        otra = self.client.post(reverse('accounts:login'), {
            'username': 'usuario_inexistente', 'password': self.clave,
        }, HTTP_X_CSRFTOKEN=self.client.cookies[settings.CSRF_COOKIE_NAME].value)
        self.assertEqual(list(otra.context['form'].non_field_errors()), errores)

    def test_sesion_previa_inactiva_no_consulta_vistas_ni_evidencia(self):
        self.sesion_previa(self.tecnico)
        self.cambiar_estado(self.tecnico, False)
        antes = self.snapshot()
        for ruta in ['/', '/tickets/', '/maintenance/', '/reports/', '/equipment/lista/',
                     '/accounts/perfil/', reverse('tickets:detalle_ticket', args=[self.ticket.pk]),
                     reverse('tickets:ver_evidencia', args=[self.ticket.pk])]:
            response = self.client.get(ruta)
            self.assertEqual(response.status_code, 302, ruta)
            self.assertIn('/accounts/login/', response.url)
        self.assertEqual(self.snapshot(), antes)

    def test_sesion_previa_inactiva_no_inicia_edita_ni_finaliza(self):
        token = self.sesion_previa(self.tecnico)
        self.cambiar_estado(self.tecnico, False)
        antes = self.snapshot()
        for nombre in ['maintenance:iniciar_atencion', 'maintenance:registrar_atencion',
                       'maintenance:finalizar_atencion']:
            response = self.client.post(reverse(nombre, args=[self.ticket.pk]),
                {'diagnostico': 'Intento bloqueado'}, HTTP_X_CSRFTOKEN=token)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.url)
            self.assertEqual(self.snapshot(), antes)

    def test_supervisor_inactivo_no_modifica_ticket(self):
        token = self.sesion_previa(self.supervisor)
        self.cambiar_estado(self.supervisor, False)
        antes = self.snapshot()
        for nombre, datos in [
            ('tickets:priorizar_ticket', {'prioridad': 'critica'}),
            ('tickets:redirigir_ticket', {'area_soporte': self.area.pk}),
            ('tickets:asignar_tecnico', {'tecnico': self.tecnico.pk}),
            ('maintenance:revisar_atencion', {'decision': 'aprobado'}),
        ]:
            response = self.client.post(reverse(nombre, args=[self.ticket.pk]),
                                        datos, HTTP_X_CSRFTOKEN=token)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.url)
            self.assertEqual(self.snapshot(), antes)

    def test_inactivo_no_se_reactiva_por_url_directa(self):
        token = self.sesion_previa(self.tecnico)
        self.cambiar_estado(self.tecnico, False)
        response = self.client.post(reverse('accounts:usuario_editar', args=[self.tecnico.pk]),
                                   {'is_active': 'on'}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 302)
        self.tecnico.refresh_from_db()
        self.assertFalse(self.tecnico.is_active)

    def test_reactivacion_administrativa_permite_nuevo_login(self):
        self.cambiar_estado(self.tecnico, False)
        self.cambiar_estado(self.tecnico, True)
        self.assertTrue(self.client.login(username=self.tecnico.username, password=self.clave))
        self.assertEqual(self.client.get(reverse('core:dashboard')).status_code, 200)

    def test_formulario_solo_expone_estado_canonico(self):
        form = UserEditForm(instance=self.tecnico)
        self.assertIn('is_active', form.fields)
        self.assertNotIn('activo_sistema', form.fields)
        response = self.administrador.get(reverse('accounts:usuario_editar', args=[self.tecnico.pk]))
        self.assertContains(response, 'name="is_active"')
        self.assertNotContains(response, 'name="activo_sistema"')

    def test_estado_false_canonico_no_se_anula_por_legado_true(self):
        self.tecnico.is_active = False
        self.tecnico.activo_sistema = True
        self.tecnico.save(update_fields=['is_active', 'activo_sistema'])
        self.assertIsNone(authenticate(username=self.tecnico.username, password=self.clave))
        self.assertFalse(puede_operar_ticket(self.tecnico, self.ticket, CONSULTAR))

    def test_reactivacion_explicita_no_depende_del_campo_legado(self):
        self.tecnico.is_active = False
        self.tecnico.activo_sistema = False
        self.tecnico.save(update_fields=['is_active', 'activo_sistema'])
        self.cambiar_estado(self.tecnico, True)
        self.assertFalse(self.tecnico.activo_sistema)
        self.assertIsNotNone(authenticate(username=self.tecnico.username, password=self.clave))

    def test_politica_central_deniega_objetos_usuario_inactivo(self):
        acciones = [CONSULTAR, VER_EVIDENCIA, *ACCIONES_GESTION, *ESTADOS_ACCION_TECNICA]
        for usuario in [self.tecnico, self.supervisor, self.solicitante, self.admin]:
            usuario.is_active = False
            for accion in acciones:
                self.assertFalse(puede_operar_ticket(usuario, self.ticket, accion))
            self.assertFalse(tiene_acceso_global(usuario))
            self.assertFalse(usuario.puede_gestionar_area(self.area))

    def test_interfaz_y_admin_reflejan_is_active(self):
        self.cambiar_estado(self.tecnico, False)
        response = self.administrador.get(reverse('accounts:usuarios_list'))
        usuario = next(u for u in response.context['usuarios'] if u.pk == self.tecnico.pk)
        self.assertFalse(usuario.is_active)
        configuracion = admin.site._registry[User]
        self.assertIn('is_active', configuracion.list_display)
        self.assertIn('is_active', configuracion.list_filter)
        self.assertNotIn('activo_sistema', configuracion.list_display)
        self.assertNotIn('activo_sistema', configuracion.get_form(
            self._request_admin(), obj=self.tecnico).base_fields)
        self.assertEqual(self.administrador.get(reverse('admin:accounts_user_changelist')).status_code, 200)

    def _request_admin(self):
        from django.test import RequestFactory
        request = RequestFactory().get('/admin/')
        request.user = self.admin
        return request

    def test_perfil_muestra_estado_canonico_y_no_legado(self):
        self.tecnico.activo_sistema = False
        self.tecnico.save(update_fields=['activo_sistema'])
        self.client.force_login(self.tecnico)
        response = self.client.get(reverse('accounts:perfil'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Habilitada')

    def test_tecnico_inactivo_no_es_seleccionable_ni_asignable(self):
        self.cambiar_estado(self.tecnico, False)
        ruta = reverse('tickets:asignar_tecnico', args=[self.ticket.pk])
        response = self.administrador.get(ruta)
        self.assertNotIn(self.tecnico, response.context['tecnicos'])
        antes = self.snapshot()
        response = self.administrador.post(ruta, {'tecnico': self.tecnico.pk},
            HTTP_X_CSRFTOKEN=self.administrador.cookies[settings.CSRF_COOKIE_NAME].value)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snapshot(), antes)

    def test_cambio_de_estado_sin_csrf_no_modifica_cuenta(self):
        response = self.administrador.post(reverse('accounts:usuario_editar', args=[self.tecnico.pk]),
                                           {'is_active': ''})
        self.assertEqual(response.status_code, 403)
        self.tecnico.refresh_from_db()
        self.assertTrue(self.tecnico.is_active)


class ReconciliacionEstadosMigrationTests(TransactionTestCase):
    """Aplica y revierte solo en la base de pruebas, sin eliminar ningún campo."""
    anterior = [('accounts', '0001_initial')]
    nueva = [('accounts', '0002_reconciliar_estado_cuentas')]

    def test_migracion_conservadora_preserva_identidades_y_bajas(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.anterior)
        try:
            apps = executor.loader.project_state(self.anterior).apps
            Historico = apps.get_model('accounts', 'User')
            ids = {}
            for activo, legado in [(True, True), (True, False), (False, True), (False, False)]:
                u = Historico.objects.create(username=f'caso_{activo}_{legado}',
                    is_active=activo, activo_sistema=legado)
                ids[(activo, legado)] = u.pk
            area = Area.objects.create(nombre='Área migración', codigo='MIG')
            servicio = Servicio.objects.create(nombre='Servicio migración', codigo='MIG')
            sala = AreaProblema.objects.create(nombre='Sala migración', codigo='MIG')
            ticket = Ticket.objects.create(codigo_ticket='MIG-ESTADO',
                solicitante_id=ids[(True, False)], servicio=servicio, area_problema=sala,
                area_soporte=area, descripcion='Registro histórico de migración')
            TicketAssignment.objects.create(ticket=ticket, tecnico_id=ids[(True, False)],
                                             asignado_por_id=ids[(True, True)])
            AtencionTecnica.objects.create(ticket=ticket, tecnico_id=ids[(True, False)])
            TicketEvent.objects.create(ticket=ticket, usuario_id=ids[(True, False)], tipo_accion='registro')
            modelos = (Ticket, TicketAssignment, AtencionTecnica, TicketEvent)
            historial = [list(m.objects.order_by('pk').values()) for m in modelos]
            executor = MigrationExecutor(connection)
            executor.migrate(self.nueva)
            Nuevo = executor.loader.project_state(self.nueva).apps.get_model('accounts', 'User')
            self.assertEqual(Nuevo.objects.count(), 4)
            for (activo, legado), pk in ids.items():
                u = Nuevo.objects.get(pk=pk)
                self.assertEqual(u.is_active, activo and legado)
                self.assertEqual(u.activo_sistema, legado)
            self.assertEqual([list(m.objects.order_by('pk').values()) for m in modelos], historial)
            # Revertir no debe reactivar la cuenta deshabilitada por reconciliación.
            MigrationExecutor(connection).migrate(self.anterior)
            self.assertFalse(Historico.objects.get(pk=ids[(True, False)]).is_active)
        finally:
            MigrationExecutor(connection).migrate(self.nueva)
