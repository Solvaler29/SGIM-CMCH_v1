"""AUD-004: semántica HTTP, CSRF real y ausencia de escrituras GET/HEAD."""
from html.parser import HTMLParser
from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import Client, TestCase
from django.urls import reverse
from accounts.models import Area, User
from core.models import Servicio, AreaProblema
from tickets.models import Ticket, TicketAssignment, TicketEvent, Satisfaccion
from .models import AtencionTecnica, RevisionSupervisor


class FormulariosParser(HTMLParser):
    """Inspecciona formularios y enlaces sin depender de su formato visual."""
    def __init__(self):
        super().__init__()
        self.formularios = []
        self.enlaces = []
        self.actual = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.actual = {**attrs, 'csrf': False, 'submit': False}
            self.formularios.append(self.actual)
        elif tag == 'input' and self.actual is not None:
            if attrs.get('name') == 'csrfmiddlewaretoken' and attrs.get('value'):
                self.actual['csrf'] = True
        elif tag == 'button' and self.actual is not None:
            self.actual['submit'] |= attrs.get('type') == 'submit'
        elif tag == 'a':
            self.enlaces.append(attrs.get('href'))

    def handle_endtag(self, tag):
        if tag == 'form':
            self.actual = None


class MetodosHttpSegurosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        area = Area.objects.create(nombre='TI ficticia', codigo='TI')
        cls.tecnico = User.objects.create_user(username='tecnico', roles='tecnico')
        cls.otro = User.objects.create_user(username='otro_tecnico', roles='tecnico')
        cls.admin = User.objects.create_user(username='admin', roles='administrador',
                                             is_staff=True, is_superuser=True)
        cls.solicitante = User.objects.create_user(username='solicitante', roles='solicitante')
        cls.tecnico.areas.add(area)
        servicio = Servicio.objects.create(nombre='Servicio ficticio', codigo='TEST')
        sala = AreaProblema.objects.create(nombre='Sala ficticia', codigo='SALA')
        cls.ticket = Ticket.objects.create(
            codigo_ticket='AUD004-TEST', solicitante=cls.solicitante,
            area_soporte=area, servicio=servicio, area_problema=sala,
            descripcion='Prueba HTTP ficticia', estado='asignada',
        )
        TicketAssignment.objects.create(ticket=cls.ticket, tecnico=cls.tecnico, asignado_por=cls.admin)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.tecnico)

    def url(self, accion):
        return reverse('maintenance:' + accion, args=[self.ticket.pk])

    def snapshot(self):
        return [list(model.objects.order_by('pk').values()) for model in (
            Ticket, TicketAssignment, AtencionTecnica, TicketEvent,
            RevisionSupervisor, Satisfaccion,
        )]

    def csrf(self):
        self.assertEqual(self.client.get(reverse('core:dashboard')).status_code, 200)
        return self.client.cookies[settings.CSRF_COOKIE_NAME].value

    def iniciar(self):
        response = self.client.post(self.url('iniciar_atencion'), HTTP_X_CSRFTOKEN=self.csrf())
        self.assertRedirects(response, reverse('tickets:detalle_ticket', args=[self.ticket.pk]))
        return AtencionTecnica.objects.get(ticket=self.ticket)

    def verificar_formulario(self, response, accion):
        parser = FormulariosParser()
        parser.feed(response.content.decode())
        formularios = [f for f in parser.formularios if f.get('action') == accion]
        self.assertEqual(len(formularios), 1)
        self.assertEqual(formularios[0].get('method', '').lower(), 'post')
        self.assertTrue(formularios[0]['csrf'])
        self.assertTrue(formularios[0]['submit'])
        self.assertNotIn(accion, parser.enlaces)

    def test_get_y_head_inicio_no_crean_atencion_ni_eventos(self):
        antes = self.snapshot()
        for metodo in ['get', 'head']:
            response = getattr(self.client, metodo)(self.url('iniciar_atencion'))
            self.assertEqual(response.status_code, 405)
            self.assertEqual(response['Allow'], 'POST')
            self.assertEqual(self.snapshot(), antes)

    def test_post_con_csrf_inicia_y_redirige(self):
        atencion = self.iniciar()
        self.ticket.refresh_from_db()
        self.assertEqual(atencion.tecnico, self.tecnico)
        self.assertIsNotNone(atencion.work_started_at)
        self.assertEqual(self.ticket.estado, 'en_atencion')
        self.assertEqual(TicketEvent.objects.filter(tipo_accion='inicio_atencion').count(), 1)

    def test_inicio_sin_csrf_o_con_token_invalido_rechazado(self):
        self.csrf()
        antes = self.snapshot()
        for headers in [{}, {'HTTP_X_CSRFTOKEN': 'token-invalido'}]:
            response = self.client.post(self.url('iniciar_atencion'), **headers)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.snapshot(), antes)

    def test_get_y_head_finalizacion_no_modifican_registros(self):
        self.iniciar()
        antes = self.snapshot()
        for metodo in ['get', 'head']:
            response = getattr(self.client, metodo)(self.url('finalizar_atencion'))
            self.assertEqual(response.status_code, 405)
            self.assertEqual(self.snapshot(), antes)

    def test_post_finaliza_con_reglas_actuales_y_redirige(self):
        atencion = self.iniciar()
        response = self.client.post(self.url('finalizar_atencion'), HTTP_X_CSRFTOKEN=self.csrf())
        self.assertRedirects(response, reverse('tickets:detalle_ticket', args=[self.ticket.pk]))
        self.ticket.refresh_from_db()
        atencion.refresh_from_db()
        self.assertEqual(self.ticket.estado, 'pendiente_validacion')
        self.assertIsNone(self.ticket.closed_at)
        self.assertTrue(atencion.finalizado_por_tecnico)
        self.assertTrue(atencion.enviado_a_revision)
        self.assertIsNotNone(atencion.work_finished_at)
        self.assertEqual(TicketEvent.objects.filter(tipo_accion='fin_atencion').count(), 1)

    def test_finalizacion_sin_csrf_rechazada_sin_efectos(self):
        self.iniciar()
        antes = self.snapshot()
        response = self.client.post(self.url('finalizar_atencion'))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.snapshot(), antes)

    def test_post_sin_autorizacion_con_csrf_no_escribe(self):
        self.iniciar()
        self.client.force_login(self.otro)
        token = self.csrf()
        antes = self.snapshot()
        for accion in ['iniciar_atencion', 'finalizar_atencion']:
            response = self.client.post(self.url(accion), HTTP_X_CSRFTOKEN=token)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(self.snapshot(), antes)

    def test_post_repetido_no_duplica_transicion_ni_fechas(self):
        self.iniciar()
        token = self.csrf()
        antes = self.snapshot()
        self.assertEqual(self.client.post(self.url('iniciar_atencion'), HTTP_X_CSRFTOKEN=token).status_code, 404)
        self.assertEqual(self.snapshot(), antes)
        self.assertEqual(self.client.post(self.url('finalizar_atencion'), HTTP_X_CSRFTOKEN=token).status_code, 302)
        final = self.snapshot()
        self.assertEqual(self.client.post(self.url('finalizar_atencion'), HTTP_X_CSRFTOKEN=token).status_code, 404)
        self.assertEqual(self.snapshot(), final)

    def test_otros_metodos_no_permitidos_no_escriben(self):
        token = self.csrf()
        antes = self.snapshot()
        for accion in ['iniciar_atencion', 'finalizar_atencion']:
            for metodo in ['put', 'patch', 'delete', 'options']:
                response = getattr(self.client, metodo)(self.url(accion), HTTP_X_CSRFTOKEN=token)
                self.assertEqual(response.status_code, 405)
                self.assertEqual(self.snapshot(), antes)

    def test_anonimo_no_inicia_ni_finaliza(self):
        self.client.logout()
        antes = self.snapshot()
        for accion in ['iniciar_atencion', 'finalizar_atencion']:
            for metodo in ['get', 'head']:
                response = getattr(self.client, metodo)(self.url(accion))
                self.assertEqual(response.status_code, 302)
            self.assertEqual(self.client.post(self.url(accion)).status_code, 403)
        self.assertEqual(self.snapshot(), antes)

    def test_logout_get_head_conservan_sesion_app_y_admin(self):
        self.client.force_login(self.admin)
        for nombre in ['accounts:logout', 'admin:logout']:
            for metodo in ['get', 'head']:
                session_key = self.client.session.session_key
                antes = self.snapshot()
                response = getattr(self.client, metodo)(reverse(nombre))
                self.assertEqual(response.status_code, 405)
                self.assertEqual(self.client.session.get('_auth_user_id'), str(self.admin.pk))
                self.assertTrue(Session.objects.filter(session_key=session_key).exists())
                self.assertEqual(self.snapshot(), antes)

    def test_logout_post_con_csrf_app_y_admin(self):
        for nombre in ['accounts:logout', 'admin:logout']:
            self.client.force_login(self.admin)
            session_key = self.client.session.session_key
            response = self.client.post(reverse(nombre), HTTP_X_CSRFTOKEN=self.csrf())
            self.assertEqual(response.status_code, 302)
            self.assertNotIn('_auth_user_id', self.client.session)
            self.assertFalse(Session.objects.filter(session_key=session_key).exists())

    def test_logout_sin_csrf_o_token_invalido_no_cierra_sesion(self):
        self.client.force_login(self.admin)
        self.csrf()
        for nombre in ['accounts:logout', 'admin:logout']:
            for headers in [{}, {'HTTP_X_CSRFTOKEN': 'token-invalido'}]:
                response = self.client.post(reverse(nombre), **headers)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.client.session.get('_auth_user_id'), str(self.admin.pk))

    def test_plantillas_inicio_fin_y_logout_son_formularios_post(self):
        detalle = reverse('tickets:detalle_ticket', args=[self.ticket.pk])
        response = self.client.get(detalle)
        self.verificar_formulario(response, self.url('iniciar_atencion'))
        self.verificar_formulario(response, reverse('accounts:logout'))
        self.iniciar()
        self.verificar_formulario(self.client.get(detalle), self.url('finalizar_atencion'))
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 200)
        self.verificar_formulario(response, reverse('admin:logout'))

    def test_formularios_y_listados_get_head_no_escriben_datos_de_negocio(self):
        self.iniciar()
        self.client.force_login(self.admin)
        rutas = ['/', '/tickets/', '/tickets/registrar/', '/reports/', '/equipment/lista/',
                 '/accounts/usuarios/', '/accounts/registro/', '/accounts/perfil/',
                 f'/accounts/usuarios/{self.tecnico.pk}/editar/']
        rutas += [reverse(nombre, args=[self.ticket.pk]) for nombre in [
            'tickets:detalle_ticket', 'tickets:priorizar_ticket', 'tickets:redirigir_ticket',
            'tickets:asignar_tecnico', 'maintenance:revisar_atencion',
        ]]
        antes = self.snapshot()
        for ruta in rutas:
            for metodo in ['get', 'head']:
                response = getattr(self.client, metodo)(ruta)
                # MVP-01: el administrador conserva lectura de sus pantallas,
                # pero ya no tiene permiso para registrar incidencias.
                esperado = 404 if ruta == reverse('tickets:registrar_ticket') else 200
                self.assertEqual(response.status_code, esperado, (ruta, metodo))
                self.assertEqual(self.snapshot(), antes)
        self.client.force_login(self.tecnico)
        antes = self.snapshot()
        for metodo in ['get', 'head']:
            self.assertEqual(getattr(self.client, metodo)(self.url('registrar_atencion')).status_code, 200)
            self.assertEqual(self.snapshot(), antes)
