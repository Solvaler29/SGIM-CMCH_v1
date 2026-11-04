"""AUD-011: datos ficticios y conexiones PostgreSQL independientes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from importlib import import_module
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
import tempfile
from io import BytesIO

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from accounts.models import Area, User
from core.models import Servicio, AreaProblema
from .models import Ticket, TicketEvent, ContadorDiarioTicket
from .codigos import LimiteCodigoTicket


class DatosCodigo:
    def setUp(self):
        super().setUp()
        self.usuario = User.objects.create_user(username='codigo_ficticio', roles='solicitante')
        self.area = Area.objects.create(nombre='TI ficticia', codigo='TI')
        self.servicio = Servicio.objects.create(nombre='Servicio ficticio', codigo='COD')
        self.sala = AreaProblema.objects.create(nombre='Sala ficticia', codigo='COD')
        self.datos = dict(solicitante_id=self.usuario.pk, area_soporte_id=self.area.pk,
                          servicio_id=self.servicio.pk, area_problema_id=self.sala.pk,
                          descripcion='Prueba ficticia')

    def crear(self):
        return Ticket.objects.create(**self.datos)


class CodigosTests(DatosCodigo, TestCase):
    def test_primero_segundo_y_dia_siguiente_utc(self):
        with patch('tickets.codigos.timezone.now', return_value=datetime(2026, 1, 2, tzinfo=timezone.utc)):
            self.assertEqual(self.crear().codigo_ticket, 'TIK-20260102-0001')
            self.assertEqual(self.crear().codigo_ticket, 'TIK-20260102-0002')
        with patch('tickets.codigos.timezone.now', return_value=datetime(2026, 1, 3, tzinfo=timezone.utc)):
            self.assertEqual(self.crear().codigo_ticket, 'TIK-20260103-0001')

    def test_supera_9999_y_agotamiento_sin_incremento(self):
        hoy = date.today()
        with patch('tickets.codigos.timezone.now', return_value=datetime.combine(hoy, datetime.min.time(), timezone.utc)):
            contador = ContadorDiarioTicket.objects.create(fecha=hoy, ultimo_correlativo=9999)
            self.assertTrue(self.crear().codigo_ticket.endswith('-10000'))
            contador.ultimo_correlativo = 9999998
            contador.save()
            self.assertEqual(len(self.crear().codigo_ticket), 20)
            with self.assertRaises(LimiteCodigoTicket):
                self.crear()
            contador.refresh_from_db()
            self.assertEqual(contador.ultimo_correlativo, 9999999)
            self.assertEqual(Ticket.objects.count(), 2)

    def test_fallo_insert_revierte_contador(self):
        with patch.object(Ticket, '_save_table', side_effect=IntegrityError('fallo ficticio')):
            with self.assertRaises(IntegrityError):
                self.crear()
        self.assertFalse(ContadorDiarioTicket.objects.exists())
        self.assertFalse(Ticket.objects.exists())

    def test_unicidad_bd_y_no_reutiliza_tras_borrado(self):
        ticket = self.crear()
        codigo = ticket.codigo_ticket
        with self.assertRaises(IntegrityError), transaction.atomic():
            Ticket.objects.create(codigo_ticket=codigo, **self.datos)
        ticket.delete()
        self.assertNotEqual(self.crear().codigo_ticket, codigo)

    def post(self, client=None, **extra):
        client = client or self.client
        client.force_login(self.usuario)
        archivo = BytesIO()
        Image.new('RGB', (2, 2)).save(archivo, format='PNG')
        datos = dict(servicio=self.servicio.pk, area_problema=self.sala.pk,
                     area_soporte=self.area.pk, descripcion='Incidencia ficticia',
                     fotografia=SimpleUploadedFile('prueba.png', archivo.getvalue(), 'image/png'))
        datos.update(extra)
        return client.post(reverse('tickets:registrar_ticket'), datos)

    def test_evento_y_ticket_atomicos(self):
        with tempfile.TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            self.assertEqual(self.post().status_code, 302)
            self.assertEqual(TicketEvent.objects.get().ticket_id, Ticket.objects.get().pk)

    def test_fallo_evento_revierte_ticket_y_contador(self):
        with tempfile.TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            with patch('tickets.views.TicketEvent.objects.create', side_effect=IntegrityError('evento ficticio')):
                with self.assertRaises(IntegrityError):
                    self.post()
        self.assertFalse(Ticket.objects.exists())
        self.assertFalse(TicketEvent.objects.exists())
        self.assertFalse(ContadorDiarioTicket.objects.exists())

    def test_csrf_y_codigo_manipulado(self):
        self.assertEqual(self.post(Client(enforce_csrf_checks=True)).status_code, 403)
        self.assertEqual(self.post(codigo_ticket='TIK-20260101-0001').status_code, 200)
        self.assertFalse(Ticket.objects.exists())
        self.assertFalse(ContadorDiarioTicket.objects.exists())

    def test_limite_http_controlado_sin_evento_ni_ticket(self):
        with patch('tickets.codigos.timezone.now', return_value=datetime(2026, 2, 3, tzinfo=timezone.utc)):
            contador = ContadorDiarioTicket.objects.create(fecha=date(2026, 2, 3), ultimo_correlativo=9999999)
            respuesta = self.post()
        self.assertContains(respuesta, 'límite diario', status_code=409)
        contador.refresh_from_db()
        self.assertEqual(contador.ultimo_correlativo, 9999999)
        self.assertFalse(Ticket.objects.exists())
        self.assertFalse(TicketEvent.objects.exists())


class ConcurrenciaCodigosTests(DatosCodigo, TransactionTestCase):
    def concurrentes(self, existente):
        self.assertEqual(connection.vendor, 'postgresql')
        hoy = date(2026, 2, 3)
        if existente:
            ContadorDiarioTicket.objects.create(fecha=hoy, ultimo_correlativo=12)
        bloqueado, liberar, segundo_listo = Event(), Event(), Event()
        pids = {}

        def trabajador(primero):
            conexion = connections['default']
            try:
                with conexion.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    pid = cursor.fetchone()[0]
                pids[primero] = pid
                if not primero:
                    segundo_listo.set()

                def retener(execute, sql, params, many, context):
                    resultado = execute(sql, params, many, context)
                    if primero and 'FOR UPDATE' in sql and 'tickets_contadordiarioticket' in sql:
                        bloqueado.set()
                        if not liberar.wait(20):
                            raise AssertionError('No se libero el contador de prueba')
                    return resultado

                with conexion.execute_wrapper(retener):
                    ticket = self.crear()
                return pid, ticket.codigo_ticket
            finally:
                conexion.close()

        with patch('tickets.codigos.timezone.now', return_value=datetime(2026, 2, 3, tzinfo=timezone.utc)):
            with ThreadPoolExecutor(max_workers=2) as executor:
                primero = executor.submit(trabajador, True)
                try:
                    self.assertTrue(bloqueado.wait(15))
                    segundo = executor.submit(trabajador, False)
                    self.assertTrue(segundo_listo.wait(15))
                    espera_real = False
                    limite = monotonic() + 15
                    while monotonic() < limite:
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT pg_blocking_pids(%s)', [pids[False]])
                            espera_real = pids[True] in cursor.fetchone()[0]
                        if espera_real:
                            break
                        sleep(0.02)
                    self.assertTrue(espera_real, 'PostgreSQL debe mostrar el bloqueo concurrente')
                finally:
                    liberar.set()
                resultados = [primero.result(timeout=20), segundo.result(timeout=20)]
        self.assertEqual(len({r[0] for r in resultados}), 2)
        self.assertEqual({r[1] for r in resultados},
                         {f'TIK-20260203-{n:04d}' for n in ([13, 14] if existente else [1, 2])})
        self.assertEqual(Ticket.objects.count(), 2)
        self.assertEqual(ContadorDiarioTicket.objects.get().ultimo_correlativo, 14 if existente else 2)

    def test_contador_existente(self):
        self.concurrentes(True)

    def test_primer_contador_simultaneo(self):
        self.concurrentes(False)


class MigracionCodigosTests(DatosCodigo, TransactionTestCase):
    anterior = [('tickets', '0003_programacion_y_asignacion_vigente')]
    nueva = [('tickets', '0004_contador_diario_ticket')]

    def setUp(self):
        super().setUp()
        MigrationExecutor(connection).migrate(self.anterior)

    def tearDown(self):
        # Exclusivamente fixtures de esta base de pruebas, nunca datos de la app.
        Ticket.objects.all().delete()
        executor = MigrationExecutor(connection)
        executor.migrate(self.nueva)
        super().tearDown()

    def test_inicializa_maximo_numerico_y_conserva_historia(self):
        for numero in [9999, 10000, 2]:
            Ticket.objects.create(codigo_ticket=f'TIK-20260102-{numero:04d}', **self.datos)
        antes = list(Ticket.objects.order_by('pk').values())
        MigrationExecutor(connection).migrate(self.nueva)
        self.assertEqual(ContadorDiarioTicket.objects.get().ultimo_correlativo, 10000)
        self.assertEqual(list(Ticket.objects.order_by('pk').values()), antes)
        with self.assertRaisesRegex(RuntimeError, 'reversión bloqueada'):
            MigrationExecutor(connection).migrate(self.anterior)
        self.assertEqual(ContadorDiarioTicket.objects.get().ultimo_correlativo, 10000)

    def test_anomalias_abortan_migracion_completa(self):
        for codigo in ['ATIPICO', 'TIK-20260230-0001', 'TIK-20260102-00001']:
            with self.subTest(codigo=codigo):
                Ticket.objects.create(codigo_ticket=codigo, **self.datos)
                with self.assertRaisesRegex(RuntimeError, 'inicialización detenida'):
                    MigrationExecutor(connection).migrate(self.nueva)
                self.assertNotIn('tickets_contadordiarioticket', connection.introspection.table_names())
                Ticket.objects.all().delete()

    def test_inspector_detecta_longitud_excesiva(self):
        funcion = import_module('tickets.migrations.0004_contador_diario_ticket').inicializar
        modelo = import_module('unittest.mock').Mock()
        modelo.objects.using.return_value.values_list.return_value.iterator.return_value = [(1, 'TIK-20260102-10000000')]
        registro = import_module('unittest.mock').Mock()
        registro.get_model.return_value = modelo
        with connection.schema_editor() as editor:
            with self.assertRaisesRegex(RuntimeError, 'longitud'):
                funcion(registro, editor)
