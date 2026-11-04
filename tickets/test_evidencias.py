"""AUD-003: archivos ficticios, almacenamiento temporal y base de pruebas."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from PIL import Image
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.test import TestCase, override_settings
from django.urls import reverse
from accounts.models import Area, User
from core.models import Servicio, AreaProblema
from maintenance.models import AtencionTecnica, RevisionSupervisor
from .models import Ticket, TicketAssignment, TicketEvent
from .permissions import VER_EVIDENCIA, puede_operar_ticket


class StoragePrivadoSinRutas(Storage):
    """Backend de prueba sin path() ni url(), como un origen privado remoto."""
    def __init__(self, contenido):
        self.contenido = contenido

    def _open(self, name, mode='rb'):
        return ContentFile(self.contenido, name=name)


class EvidenciasPrivadasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ti = Area.objects.create(nombre='TI ficticia', codigo='TI')
        ic = Area.objects.create(nombre='IC ficticia', codigo='IC')
        cls.solicitante = User.objects.create_user(username='propietario', roles='solicitante')
        cls.ajeno = User.objects.create_user(username='ajeno', roles='solicitante')
        cls.supervisor = User.objects.create_user(username='supervisor_ti', roles='supervisor')
        cls.supervisor.areas.add(ti)
        cls.supervisor_ajeno = User.objects.create_user(username='supervisor_ic', roles='supervisor')
        cls.supervisor_ajeno.areas.add(ic)
        cls.tecnico = User.objects.create_user(username='tecnico_ti', roles='tecnico')
        cls.tecnico.areas.add(ti)
        cls.admin = User.objects.create_user(username='administrador', roles='administrador')
        servicio = Servicio.objects.create(nombre='Servicio ficticio', codigo='TEST')
        sala = AreaProblema.objects.create(nombre='Sala ficticia', codigo='SALA')
        cls.ticket = Ticket.objects.create(
            codigo_ticket='FOTO-TI', solicitante=cls.solicitante, servicio=servicio,
            area_problema=sala, area_soporte=ti, descripcion='Prueba de fotografía',
        )
        cls.otro_ticket = Ticket.objects.create(
            codigo_ticket='FOTO-IC', solicitante=cls.ajeno, servicio=servicio,
            area_problema=sala, area_soporte=ic, descripcion='Otra fotografía',
        )
        TicketAssignment.objects.create(ticket=cls.ticket, tecnico=cls.tecnico, asignado_por=cls.admin)

    def setUp(self):
        temporal = TemporaryDirectory(prefix='sgim-aud003-')
        self.addCleanup(temporal.cleanup)
        self.media_root = temporal.name
        configuracion = override_settings(MEDIA_ROOT=self.media_root, DEBUG=True)
        configuracion.enable()
        self.addCleanup(configuracion.disable)
        self.contenido = self.imagen('red')
        self.otro_contenido = self.imagen('blue')
        self.ticket.fotografia.save('prueba.png', ContentFile(self.contenido), save=True)
        self.otro_ticket.fotografia.save('otra.png', ContentFile(self.otro_contenido), save=True)

    @staticmethod
    def imagen(color):
        buffer = BytesIO()
        Image.new('RGB', (2, 2), color).save(buffer, format='PNG')
        return buffer.getvalue()

    def url(self, ticket=None):
        return reverse('tickets:ver_evidencia', args=[(ticket or self.ticket).pk])

    def snapshot(self):
        return [list(model.objects.order_by('pk').values()) for model in (
            Ticket, TicketAssignment, AtencionTecnica, RevisionSupervisor, TicketEvent,
        )]

    def comprobar_entrega(self, usuario):
        self.client.force_login(usuario)
        antes = self.snapshot()
        response = self.client.get(self.url())
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), self.contenido)
            self.assertEqual(response['Content-Type'], 'image/png')
            self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
            self.assertIn('private', response['Cache-Control'])
            self.assertIn('no-store', response['Cache-Control'])
            self.assertNotIn(self.media_root, str(dict(response.items())))
            self.assertNotIn(self.ticket.fotografia.name, response['Content-Disposition'])
        finally:
            if not response.closed:
                response.close()
        self.assertEqual(self.snapshot(), antes)

    def comprobar_denegacion(self, usuario, url=None, status=404):
        if usuario is not None:
            self.client.force_login(usuario)
        antes = self.snapshot()
        storage = self.ticket.fotografia.storage
        with patch.object(storage, 'open') as abrir:
            response = self.client.get(url or self.url())
            self.assertEqual(response.status_code, status)
            abrir.assert_not_called()
        self.assertNotIn(self.media_root.encode(), response.content)
        self.assertEqual(self.snapshot(), antes)

    def test_solicitante_propietario_consulta_fotografia(self):
        self.comprobar_entrega(self.solicitante)

    def test_solicitante_ajeno_denegado_antes_de_abrir_archivo(self):
        self.comprobar_denegacion(self.ajeno)

    def test_supervisor_autorizado_consulta(self):
        self.comprobar_entrega(self.supervisor)

    def test_supervisor_otra_area_denegado(self):
        self.comprobar_denegacion(self.supervisor_ajeno)

    def test_tecnico_con_asignacion_vigente_consulta(self):
        self.comprobar_entrega(self.tecnico)

    def test_tecnico_sin_asignacion_vigente_denegado(self):
        self.ticket.asignaciones.update(activo=False)
        self.comprobar_denegacion(self.tecnico)

    def test_administrador_operativo_consulta(self):
        self.comprobar_entrega(self.admin)

    def test_anonimo_no_obtiene_contenido(self):
        self.comprobar_denegacion(None, status=302)

    def test_ticket_inexistente_no_abre_storage(self):
        self.comprobar_denegacion(self.solicitante,
                                  reverse('tickets:ver_evidencia', args=[999999]))

    def test_ticket_sin_fotografia(self):
        # Se quita solo la referencia en la BD temporal, no se elimina el archivo.
        self.ticket.fotografia = ''
        self.ticket.save(update_fields=['fotografia'])
        self.comprobar_denegacion(self.solicitante)

    def test_archivo_referenciado_inexistente_sin_trazas_ni_rutas(self):
        self.ticket.fotografia = 'evidencias/no-existe.png'
        self.ticket.save(update_fields=['fotografia'])
        self.client.force_login(self.solicitante)
        antes = self.snapshot()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.media_root.encode(), response.content)
        self.assertNotIn(b'Traceback', response.content)
        self.assertEqual(self.snapshot(), antes)

    def test_url_media_antigua_no_publica_archivo_con_debug_true(self):
        antigua = '/media/' + self.ticket.fotografia.name
        self.assertTrue(Path(self.media_root, self.ticket.fotografia.name).is_file())
        for usuario in [None, self.ajeno, self.solicitante, self.admin]:
            self.client.logout()
            self.comprobar_denegacion(usuario, antigua)

    def test_identificador_manipulado_no_expone_otra_evidencia(self):
        self.comprobar_denegacion(self.solicitante, self.url(self.otro_ticket))

    def test_parametros_de_ruta_o_archivo_del_cliente_se_ignoran(self):
        self.client.force_login(self.solicitante)
        response = self.client.get(self.url(), {
            'path': self.otro_ticket.fotografia.name, 'filename': '../../.env',
            'ticket_id': self.otro_ticket.pk,
        })
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), self.contenido)
        finally:
            if not response.closed:
                response.close()

    def test_referencias_persistidas_con_traversal_o_ruta_absoluta_denegadas(self):
        for nombre in ['../fuera.png', 'evidencias/../../fuera.png', '/privado/foto.png',
                       'C:/privado/foto.png', '..\\fuera.png', 'C:foto.png']:
            with self.subTest(nombre=nombre):
                self.ticket.fotografia = nombre
                self.ticket.save(update_fields=['fotografia'])
                self.comprobar_denegacion(self.solicitante)

    def test_plantilla_usa_ruta_autorizada_y_no_url_de_storage(self):
        self.client.force_login(self.solicitante)
        response = self.client.get(reverse('tickets:detalle_ticket', args=[self.ticket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.url(), count=2)
        self.assertNotContains(response, '/media/')
        self.assertNotContains(response, self.ticket.fotografia.name)

    def test_storage_privado_sin_path_ni_url_compatible(self):
        backend = StoragePrivadoSinRutas(self.contenido)
        with patch.object(Ticket._meta.get_field('fotografia'), 'storage', backend):
            self.comprobar_entrega(self.solicitante)
            self.client.force_login(self.solicitante)
            response = self.client.get(reverse('tickets:detalle_ticket', args=[self.ticket.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, self.url())

    def test_lectura_no_habilita_modificacion_o_eliminacion(self):
        self.assertTrue(puede_operar_ticket(self.solicitante, self.ticket, VER_EVIDENCIA))
        for accion in ['modificar_evidencia', 'eliminar_evidencia']:
            self.assertFalse(puede_operar_ticket(self.admin, self.ticket, accion))
        self.client.force_login(self.solicitante)
        antes = self.snapshot()
        for metodo in ['post', 'put', 'delete']:
            self.assertEqual(getattr(self.client, metodo)(self.url()).status_code, 405)
        self.assertEqual(self.snapshot(), antes)

    def test_error_de_lectura_storage_no_expone_ruta_interna(self):
        self.client.force_login(self.solicitante)
        with patch.object(self.ticket.fotografia.storage, 'open',
                          side_effect=PermissionError('Ruta interna ' + self.media_root)):
            response = self.client.get(self.url())
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.media_root.encode(), response.content)
        self.assertNotIn(b'Traceback', response.content)
