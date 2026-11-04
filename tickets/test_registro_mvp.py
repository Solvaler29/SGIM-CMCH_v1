"""MVP-01: registro exclusivo de solicitantes; solo datos ficticios."""
from io import BytesIO
from pathlib import Path
import tempfile
from unittest.mock import patch

from PIL import Image
from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from .models import Ticket, TicketEvent, TicketAssignment, ContadorDiarioTicket
from .permissions import puede_registrar_incidencia
from .test_codigos import DatosCodigo
from .views import registrar_ticket


class RegistroMVPTests(DatosCodigo, TestCase):
    def setUp(self):
        super().setUp()
        self.carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(self.carpeta.cleanup)
        contexto = override_settings(MEDIA_ROOT=self.carpeta.name)
        contexto.enable()
        self.addCleanup(contexto.disable)
        self.roles = {}
        for rol in ('tecnico', 'supervisor', 'administrador'):
            usuario = User.objects.create_user(username='mvp_' + rol, roles=rol)
            usuario.areas.add(self.area)
            self.roles[rol] = usuario
        self.superusuario = User.objects.create_user(
            username='mvp_superusuario', roles='administrador', is_superuser=True, is_staff=True,
        )
        self.inactivo = User.objects.create_user(username='mvp_inactivo', roles='solicitante', is_active=False)
        self.ticket = Ticket.objects.create(codigo_ticket='MVP-FICTICIO', **self.datos)
        TicketAssignment.objects.create(
            ticket=self.ticket, tecnico=self.roles['tecnico'], asignado_por=self.roles['administrador'],
        )
        self.url = reverse('tickets:registrar_ticket')

    def datos_post(self):
        imagen = BytesIO()
        Image.new('RGB', (2, 2)).save(imagen, format='PNG')
        return dict(servicio=self.servicio.pk, area_problema=self.sala.pk,
                    area_soporte=self.area.pk, descripcion='Incidencia ficticia MVP',
                    fotografia=SimpleUploadedFile('mvp.png', imagen.getvalue(), 'image/png'))

    def snapshot(self):
        return [list(modelo.objects.order_by('pk').values()) for modelo in
                (Ticket, TicketEvent, ContadorDiarioTicket)]

    def rechazar(self, usuario, esperado):
        cliente = Client()
        if usuario is not None:
            cliente.force_login(usuario)
        antes = self.snapshot()
        with patch('tickets.codigos.reservar_codigo') as reservar:
            for metodo in ('get', 'post'):
                with self.subTest(usuario=usuario, metodo=metodo):
                    respuesta = getattr(cliente, metodo)(self.url, self.datos_post() if metodo == 'post' else {})
                    self.assertEqual(respuesta.status_code, esperado)
                    if esperado == 302:
                        self.assertIn(reverse('accounts:login'), respuesta.url)
                    self.assertEqual(self.snapshot(), antes)
            reservar.assert_not_called()
        self.assertEqual(list(Path(self.carpeta.name).iterdir()), [])

    def test_solicitante_activo_abre_formulario(self):
        self.client.force_login(self.usuario)
        antes = self.snapshot()
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.snapshot(), antes)

    def test_solicitante_activo_registra_ticket_evento_y_codigo(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.post(self.url, self.datos_post())
        self.assertEqual(respuesta.status_code, 302)
        ticket = Ticket.objects.exclude(pk=self.ticket.pk).get()
        self.assertEqual(ticket.solicitante, self.usuario)
        self.assertRegex(ticket.codigo_ticket, r'^TIK-[0-9]{8}-0001$')
        self.assertEqual(TicketEvent.objects.get().ticket, ticket)
        self.assertEqual(ContadorDiarioTicket.objects.get().ultimo_correlativo, 1)

    def test_tecnico_no_abre_ni_envia(self):
        self.rechazar(self.roles['tecnico'], 404)

    def test_supervisor_no_abre_ni_envia(self):
        self.rechazar(self.roles['supervisor'], 404)

    def test_administrador_no_abre_ni_envia(self):
        self.rechazar(self.roles['administrador'], 404)

    def test_superusuario_no_obtiene_excepcion(self):
        self.rechazar(self.superusuario, 404)

    def test_inactivo_no_registra(self):
        self.rechazar(self.inactivo, 302)

    def test_anonimo_no_registra(self):
        self.rechazar(None, 302)

    def test_guardia_rechaza_inactivo_aun_con_usuario_en_request(self):
        factory = RequestFactory()
        for metodo in ('get', 'post'):
            request = getattr(factory, metodo)(self.url)
            request.user = self.inactivo
            with self.assertRaises(Http404):
                registrar_ticket(request)

    def test_navegacion_por_rol_en_todas_las_pantallas(self):
        urls = [reverse('core:dashboard'), reverse('tickets:lista_tickets'),
                reverse('tickets:detalle_ticket', args=[self.ticket.pk]),
                reverse('equipment:lista_equipos'), reverse('maintenance:lista_atenciones'),
                reverse('accounts:perfil')]
        for usuario in [self.usuario, *self.roles.values(), self.superusuario]:
            self.client.force_login(usuario)
            for url in urls:
                with self.subTest(usuario=usuario.username, url=url):
                    respuesta = self.client.get(url)
                    self.assertEqual(respuesta.status_code, 200)
                    self.assertContains(respuesta, 'Cerrar')
                    if usuario == self.usuario:
                        self.assertContains(respuesta, 'href="' + self.url + '"')
                        self.assertContains(respuesta, 'Registrar incidencia')
                    else:
                        self.assertNotContains(respuesta, 'href="' + self.url + '"')

    def test_estados_vacios_no_muestran_registro_a_otros_roles(self):
        TicketAssignment.objects.all().delete()
        self.ticket.delete()
        for usuario in self.roles.values():
            self.client.force_login(usuario)
            for url in (reverse('core:dashboard'), reverse('tickets:lista_tickets')):
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 200)
                self.assertNotContains(respuesta, 'href="' + self.url + '"')
                self.assertContains(respuesta, 'No ')

    def test_politica_y_plantilla_para_anonimo_inactivo_y_staff(self):
        for usuario in (AnonymousUser(), self.inactivo, self.superusuario):
            self.assertFalse(puede_registrar_incidencia(usuario))
            request = RequestFactory().get('/')
            request.user = usuario
            self.assertNotIn('href="' + self.url + '"', render_to_string('base.html', request=request))
        self.usuario.is_staff = True
        self.usuario.is_superuser = True
        self.assertTrue(puede_registrar_incidencia(self.usuario))

    def test_no_se_puede_suplantar_rol_ni_solicitante_desde_post(self):
        self.client.force_login(self.roles['tecnico'])
        datos = self.datos_post()
        datos.update(roles='solicitante', solicitante=self.usuario.pk, is_active=True)
        antes = self.snapshot()
        self.assertEqual(self.client.post(self.url, datos).status_code, 404)
        self.assertEqual(self.snapshot(), antes)

    def test_csrf_se_mantiene_y_token_valido_permite_registro(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)
        antes = self.snapshot()
        self.assertEqual(cliente.post(self.url, self.datos_post()).status_code, 403)
        self.assertEqual(self.snapshot(), antes)
        respuesta = cliente.get(self.url)
        token = respuesta.cookies['csrftoken'].value
        self.assertEqual(cliente.post(self.url, self.datos_post(), HTTP_X_CSRFTOKEN=token).status_code, 302)
