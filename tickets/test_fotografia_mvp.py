"""MVP-02: imágenes reales generadas con Pillow, sin cámara física ni datos clínicos."""
from io import BytesIO
import tempfile
from unittest.mock import patch

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Ticket, TicketEvent, ContadorDiarioTicket
from .test_codigos import DatosCodigo


class FotografiaMVPTests(DatosCodigo, TestCase):
    def setUp(self):
        super().setUp()
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        contexto = override_settings(MEDIA_ROOT=carpeta.name)
        contexto.enable()
        self.addCleanup(contexto.disable)
        self.client.force_login(self.usuario)
        self.url = reverse('tickets:registrar_ticket')

    def foto(self, formato='PNG', nombre='foto.png', tamano=None, mime='image/png'):
        memoria = BytesIO()
        Image.new('RGB', (3, 3)).save(memoria, format=formato)
        datos = memoria.getvalue()
        if tamano:
            datos += b'\0' * (tamano - len(datos))
        return SimpleUploadedFile(nombre, datos, mime)

    def payload(self, archivo=None, campo='fotografia'):
        datos = dict(servicio=self.servicio.pk, area_problema=self.sala.pk,
                     area_soporte=self.area.pk, descripcion='Fotografia ficticia')
        if archivo:
            datos[campo] = archivo
        return datos

    def sin_persistencia(self):
        self.assertFalse(Ticket.objects.exists())
        self.assertFalse(TicketEvent.objects.exists())
        self.assertFalse(ContadorDiarioTicket.objects.exists())

    def test_carga_valida_conserva_codigo_evento_y_autor_de_sesion(self):
        datos = self.payload(self.foto())
        datos['solicitante'] = '999999'
        self.assertEqual(self.client.post(self.url, datos).status_code, 302)
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.solicitante, self.usuario)
        self.assertRegex(ticket.codigo_ticket, r'^TIK-[0-9]{8}-0001$')
        self.assertEqual(TicketEvent.objects.get().tipo_accion, 'registro')
        self.assertEqual(ContadorDiarioTicket.objects.get().ultimo_correlativo, 1)

    def test_archivo_jpeg_generado_como_canvas(self):
        self.assertEqual(self.client.post(self.url, self.payload(
            self.foto('JPEG', 'captura.jpg', mime='image/jpeg'))).status_code, 302)
        self.assertTrue(Ticket.objects.get().fotografia.name.endswith('.jpg'))

    def test_captura_nativa_utiliza_mismo_campo_y_almacenamiento(self):
        self.assertEqual(self.client.post(self.url, self.payload(
            self.foto('JPEG', 'movil.jpg', mime='image/jpeg'), 'fotografia_camara')).status_code, 302)
        self.assertTrue(Ticket.objects.get().fotografia.name.startswith('evidencias/'))
        self.assertEqual(TicketEvent.objects.count(), 1)

    def test_archivos_falsos_o_danados_no_crean_datos(self):
        for contenido in (b'<script>alert(1)</script>', b'GIF89a', b'no soy una imagen'):
            respuesta = self.client.post(self.url, self.payload(SimpleUploadedFile('falsa.jpg', contenido, 'image/jpeg')))
            self.assertEqual(respuesta.status_code, 200)
            self.assertTrue(respuesta.context['form'].errors.get('fotografia'))
            self.sin_persistencia()

    def test_formato_real_y_extension_deben_coincidir(self):
        for formato, nombre in [('GIF', 'falsa.png'), ('PNG', 'falsa.jpg'), ('BMP', 'falsa.jpg')]:
            respuesta = self.client.post(self.url, self.payload(self.foto(formato, nombre)))
            self.assertTrue(respuesta.context['form'].errors.get('fotografia'))
            self.sin_persistencia()

    def test_no_confia_en_mime_del_navegador(self):
        respuesta = self.client.post(self.url, self.payload(self.foto(mime='application/octet-stream')))
        self.assertEqual(respuesta.status_code, 302)

    def test_limite_exacto_de_cinco_mb(self):
        respuesta = self.client.post(self.url, self.payload(self.foto(tamano=5 * 1024 * 1024)))
        self.assertEqual(respuesta.status_code, 302)

    def test_mayor_a_cinco_mb_rechazado(self):
        respuesta = self.client.post(self.url, self.payload(self.foto(tamano=5 * 1024 * 1024 + 1)))
        self.assertContains(respuesta, 'no debe superar los 5 MB')
        self.sin_persistencia()

    def test_fotografia_sigue_siendo_obligatoria(self):
        respuesta = self.client.post(self.url, self.payload())
        self.assertTrue(respuesta.context['form'].errors.get('fotografia'))
        self.sin_persistencia()

    def test_dos_fuentes_simultaneas_rechazadas(self):
        datos = self.payload(self.foto())
        datos['fotografia_camara'] = self.foto('JPEG', 'captura.jpg')
        respuesta = self.client.post(self.url, datos)
        self.assertContains(respuesta, 'Selecciona una sola fotografía')
        self.sin_persistencia()

    def test_interfaz_dos_opciones_etiquetas_y_recursos_locales(self):
        respuesta = self.client.get(self.url)
        for texto in ('Tomar fotografía', 'Subir fotografía', 'capture="environment"',
                      'id="imagenFoto"', 'id="dialogoCamara"', 'Usar fotografía',
                      'for="id_descripcion"', 'registro_fotografia.js', 'Reporta:'):
            self.assertContains(respuesta, texto)
        self.assertNotContains(respuesta, 'name="solicitante"')

    def test_evidencia_capturada_se_entrega_por_ruta_privada(self):
        self.client.post(self.url, self.payload(self.foto(), 'fotografia_camara'))
        ticket = Ticket.objects.get()
        respuesta = self.client.get(reverse('tickets:ver_evidencia', args=[ticket.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'image/png')
        b''.join(respuesta.streaming_content)
        self.assertEqual(self.client.get('/media/' + ticket.fotografia.name).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('tickets:ver_evidencia', args=[ticket.pk])).status_code, 302)

    def test_error_evento_revierte_ticket_y_codigo_en_captura(self):
        with patch('tickets.views.TicketEvent.objects.create', side_effect=IntegrityError('fallo ficticio')):
            with self.assertRaises(IntegrityError):
                self.client.post(self.url, self.payload(self.foto(), 'fotografia_camara'))
        self.sin_persistencia()

    def test_error_conserva_descripcion_e_indica_reseleccionar_imagen(self):
        datos = self.payload(self.foto())
        datos['area_soporte'] = '999999'
        respuesta = self.client.post(self.url, datos)
        self.assertContains(respuesta, 'Fotografia ficticia')
        self.assertContains(respuesta, 'vuelve a seleccionar')
        self.sin_persistencia()
