"""AUD-010: validación, historia, migraciones y concurrencia PostgreSQL real."""
import threading
import time
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from unittest.mock import patch
from django.conf import settings
from django.db import connection, connections, transaction, IntegrityError
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, Area
from core.models import Servicio, AreaProblema
from maintenance.models import AtencionTecnica, RevisionSupervisor
from .models import Ticket, TicketAssignment, TicketEvent
from .views import _registrar_asignacion


class DatosAsignacion:
    def crear_datos(self):
        self.ti = Area.objects.create(nombre='TI ficticia', codigo='TI')
        self.ic = Area.objects.create(nombre='IC ficticia', codigo='IC')
        self.supervisor = User.objects.create_user(username='supervisor', roles='supervisor')
        self.supervisor.areas.add(self.ti)
        self.admin = User.objects.create_user(username='admin', roles='administrador')
        self.tecnico_a = User.objects.create_user(username='tecnico_a', roles='tecnico')
        self.tecnico_b = User.objects.create_user(username='tecnico_b', roles='tecnico')
        self.ajeno = User.objects.create_user(username='ajeno', roles='tecnico')
        self.inactivo = User.objects.create_user(username='inactivo', roles='tecnico', is_active=False)
        self.solicitante = User.objects.create_user(username='solicitante', roles='solicitante')
        for u in [self.tecnico_a, self.tecnico_b, self.inactivo]:
            u.areas.add(self.ti)
        self.ajeno.areas.add(self.ic)
        servicio = Servicio.objects.create(nombre='Servicio ficticio', codigo='TEST')
        sala = AreaProblema.objects.create(nombre='Sala ficticia', codigo='SALA')
        self.ticket = Ticket.objects.create(codigo_ticket='AUD010-TEST', solicitante=self.solicitante,
            servicio=servicio, area_problema=sala, area_soporte=self.ti, descripcion='Prueba asignación')
        self.url = reverse('tickets:asignar_tecnico', args=[self.ticket.pk])

    def snapshot(self):
        return [list(m.objects.order_by('pk').values()) for m in
                (Ticket, TicketAssignment, TicketEvent, AtencionTecnica, RevisionSupervisor)]


class AsignacionesTests(DatosAsignacion, TestCase):
    def setUp(self):
        self.crear_datos()
        self.client.force_login(self.supervisor)

    def asignar(self, tecnico=None, fecha='2026-11-20T10:30'):
        return self.client.post(self.url, {'tecnico': (tecnico or self.tecnico_a).pk, 'scheduled_at': fecha})

    def test_asignacion_valida_y_resumen_coherente(self):
        self.assertEqual(self.asignar().status_code, 302)
        vigente = self.ticket.asignaciones.get(activo=True)
        self.ticket.refresh_from_db()
        self.assertEqual(vigente.tecnico, self.tecnico_a)
        self.assertEqual(vigente.asignado_por, self.supervisor)
        self.assertIsNotNone(vigente.scheduled_at)
        self.assertEqual(vigente.scheduled_at, self.ticket.scheduled_at)
        self.assertEqual(TicketEvent.objects.get().tipo_accion, 'asignacion')

    def test_identificadores_no_elegibles_rechazados_sin_escrituras(self):
        for identificador in ['', 'abc', 999999, self.inactivo.pk, self.ajeno.pk, self.solicitante.pk]:
            with self.subTest(tecnico=identificador):
                antes = self.snapshot()
                response = self.client.post(self.url, {'tecnico': identificador})
                self.assertEqual(response.status_code, 400)
                self.assertIn('tecnico', response.context['form'].errors)
                self.assertEqual(self.snapshot(), antes)

    def test_fecha_invalida_no_desactiva_asignacion_previa(self):
        self.asignar()
        antes = self.snapshot()
        response = self.asignar(self.tecnico_b, 'fecha-invalida')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snapshot(), antes)

    def test_no_autorizados_no_se_asignan_a_si_mismos(self):
        otro_supervisor = User.objects.create_user(username='supervisor_ic', roles='supervisor')
        otro_supervisor.areas.add(self.ic)
        for usuario in [self.tecnico_a, self.solicitante, otro_supervisor]:
            self.client.force_login(usuario)
            antes = self.snapshot()
            self.assertEqual(self.asignar().status_code, 404)
            self.assertEqual(self.snapshot(), antes)

    def test_administrador_global_respeta_elegibilidad(self):
        self.client.force_login(self.admin)
        antes = self.snapshot()
        self.assertEqual(self.asignar(self.ajeno).status_code, 400)
        self.assertEqual(self.snapshot(), antes)
        self.assertEqual(self.asignar().status_code, 302)

    def test_reasignacion_preserva_programacion_autor_fecha_e_intervencion(self):
        self.asignar()
        anterior = self.ticket.asignaciones.get(activo=True)
        datos = TicketAssignment.objects.values().get(pk=anterior.pk)
        AtencionTecnica.objects.create(ticket=self.ticket, tecnico=self.tecnico_a,
                                      diagnostico='Intervención anterior', work_started_at=timezone.now())
        intervenciones = list(AtencionTecnica.objects.values())
        self.assertEqual(self.asignar(self.tecnico_b, '2026-11-21T14:00').status_code, 302)
        anterior.refresh_from_db()
        datos['activo'] = False
        self.assertEqual(TicketAssignment.objects.values().get(pk=anterior.pk), datos)
        self.assertEqual(list(AtencionTecnica.objects.values()), intervenciones)
        actual = self.ticket.asignaciones.get(activo=True)
        self.ticket.refresh_from_db()
        self.assertEqual(actual.tecnico, self.tecnico_b)
        self.assertEqual(self.ticket.scheduled_at, actual.scheduled_at)
        self.assertEqual(TicketEvent.objects.filter(tipo_accion='reasignacion').count(), 1)
        detalle = self.client.get(reverse('tickets:detalle_ticket', args=[self.ticket.pk]))
        self.assertContains(detalle, 'Atención programada')

    def test_restriccion_bd_impide_dos_vigentes_permite_historicas(self):
        self.asignar()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TicketAssignment.objects.create(ticket=self.ticket, tecnico=self.tecnico_b, asignado_por=self.admin)
        for _ in range(2):
            TicketAssignment.objects.create(ticket=self.ticket, tecnico=self.tecnico_b,
                                            asignado_por=self.admin, activo=False)
        self.assertEqual(self.ticket.asignaciones.filter(activo=True).count(), 1)

    def test_reenvio_identico_no_duplica_ni_reinicia_estado(self):
        self.asignar()
        self.ticket.estado = 'en_atencion'
        self.ticket.save(update_fields=['estado'])
        antes = self.snapshot()
        self.assertEqual(self.asignar().status_code, 302)
        self.assertEqual(self.snapshot(), antes)

    def test_programacion_vacia_conserva_anterior_y_actualiza_resumen_a_null(self):
        self.asignar()
        anterior = self.ticket.asignaciones.get(activo=True)
        self.assertEqual(self.asignar(self.tecnico_b, '').status_code, 302)
        anterior.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertIsNotNone(anterior.scheduled_at)
        self.assertIsNone(self.ticket.scheduled_at)
        self.assertIsNone(self.ticket.asignaciones.get(activo=True).scheduled_at)

    def test_ticket_cerrado_no_admite_asignacion_ordinaria(self):
        for estado, cierre in [('cerrada_tecnicamente', None), ('asignada', timezone.now())]:
            self.ticket.estado, self.ticket.closed_at = estado, cierre
            self.ticket.save(update_fields=['estado', 'closed_at'])
            antes = self.snapshot()
            for metodo in ['get', 'post']:
                self.assertEqual(getattr(self.client, metodo)(self.url, {'tecnico': self.tecnico_a.pk}).status_code, 404)
                self.assertEqual(self.snapshot(), antes)

    def test_fallo_despues_de_escrituras_revierte_toda_la_operacion(self):
        self.asignar()
        antes = self.snapshot()
        with patch('tickets.views.TicketEvent.objects.create', side_effect=RuntimeError('Fallo ficticio')):
            with self.assertRaises(RuntimeError):
                self.asignar(self.tecnico_b)
        self.assertEqual(self.snapshot(), antes)

    def test_error_postgresql_de_serializacion_devuelve_409_y_revierte(self):
        self.asignar()
        antes = self.snapshot()
        def error_bd(*args, **kwargs):
            with connection.cursor() as cursor:
                cursor.execute("DO $$ BEGIN RAISE EXCEPTION 'Conflicto ficticio' USING ERRCODE = '40001'; END $$;")
        with patch('tickets.views.TicketEvent.objects.create', side_effect=error_bd):
            response = self.asignar(self.tecnico_b)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.snapshot(), antes)

    def test_csrf_y_metodos_de_lectura(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.supervisor)
        antes = self.snapshot()
        for metodo in ['get', 'head']:
            self.assertEqual(getattr(client, metodo)(self.url).status_code, 200)
        self.assertEqual(client.post(self.url, {'tecnico': self.tecnico_a.pk}).status_code, 403)
        self.assertEqual(self.snapshot(), antes)
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        self.assertEqual(client.post(self.url, {'tecnico': self.tecnico_a.pk}, HTTP_X_CSRFTOKEN=token).status_code, 302)

    def test_prioridad_con_objeto_antiguo_no_sobrescribe_programacion(self):
        self.asignar()
        antiguo = Ticket.objects.get(pk=self.ticket.pk)
        self.asignar(self.tecnico_b, '2026-11-21T14:00')
        programacion = self.ticket.asignaciones.get(activo=True).scheduled_at
        with patch('tickets.views.obtener_ticket_autorizado', return_value=antiguo):
            response = self.client.post(reverse('tickets:priorizar_ticket', args=[self.ticket.pk]),
                                        {'prioridad': 'alta'})
        self.assertEqual(response.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.scheduled_at, programacion)
        self.assertEqual(self.ticket.prioridad, 'alta')

    def test_estados_tecnicos_con_objeto_antiguo_no_sobrescriben_programacion(self):
        self.asignar()
        fecha_anterior = self.ticket.asignaciones.get(activo=True).scheduled_at
        self.asignar(self.tecnico_a, '2026-11-21T14:00')
        programacion = self.ticket.asignaciones.get(activo=True).scheduled_at
        self.client.force_login(self.tecnico_a)
        for accion in ['iniciar_atencion', 'finalizar_atencion']:
            antiguo = Ticket.objects.get(pk=self.ticket.pk)
            antiguo.scheduled_at = fecha_anterior
            atencion = self.ticket.atenciones.first()
            # Simula una instancia leída antes de que se confirmara la nueva fecha.
            with patch('maintenance.views.obtener_contexto_atencion_autorizado',
                       return_value=(antiguo, atencion)):
                response = self.client.post(reverse('maintenance:' + accion, args=[self.ticket.pk]))
            self.assertEqual(response.status_code, 302)
            self.ticket.refresh_from_db()
            self.assertEqual(self.ticket.scheduled_at, programacion)
        self.client.force_login(self.supervisor)
        antiguo = Ticket.objects.get(pk=self.ticket.pk)
        antiguo.scheduled_at = fecha_anterior
        with patch('maintenance.views.obtener_ticket_autorizado', return_value=antiguo):
            response = self.client.post(reverse('maintenance:revisar_atencion', args=[self.ticket.pk]),
                                        {'decision': 'aprobado', 'justificacion': 'Prueba ficticia'})
        self.assertEqual(response.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.scheduled_at, programacion)


class AsignacionesConcurrentesTests(DatosAsignacion, TransactionTestCase):
    def setUp(self):
        self.crear_datos()

    def ejecutar_conexiones_independientes(self, mismo_tecnico=False):
        self.assertEqual(connection.vendor, 'postgresql')
        dentro = threading.Event()
        liberar = threading.Event()
        pids = Queue()
        local = threading.local()
        original = _registrar_asignacion

        def persistir(*args, **kwargs):
            if local.nombre == 'primera':
                dentro.set()
                if not liberar.wait(15):
                    raise RuntimeError('Tiempo agotado esperando liberar el bloqueo de prueba')
            return original(*args, **kwargs)

        def solicitud(nombre, tecnico_id, fecha):
            connections.close_all()
            try:
                local.nombre = nombre
                client = Client()
                client.force_login(User.objects.get(pk=self.supervisor.pk))
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    pids.put((nombre, cursor.fetchone()[0]))
                return client.post(self.url, {'tecnico': tecnico_id, 'scheduled_at': fecha}).status_code
            finally:
                connections.close_all()

        with patch('tickets.views._registrar_asignacion', side_effect=persistir), ThreadPoolExecutor(max_workers=2) as pool:
            primera = pool.submit(solicitud, 'primera', self.tecnico_a.pk, '2026-11-20T10:30')
            try:
                self.assertTrue(dentro.wait(10))
                nombre1, pid1 = pids.get(timeout=5)
                segunda = pool.submit(solicitud, 'segunda',
                    self.tecnico_a.pk if mismo_tecnico else self.tecnico_b.pk,
                    '2026-11-20T10:30' if mismo_tecnico else '2026-11-21T14:00')
                nombre2, pid2 = pids.get(timeout=5)
                self.assertNotEqual(pid1, pid2)
                self.assertEqual((nombre1, nombre2), ('primera', 'segunda'))
                bloqueada = False
                limite = time.monotonic() + 10
                while time.monotonic() < limite:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT %s = ANY(pg_blocking_pids(%s))', [pid1, pid2])
                        bloqueada = cursor.fetchone()[0]
                    if bloqueada:
                        break
                    time.sleep(0.02)
                self.assertTrue(bloqueada, 'La segunda conexión debe esperar el bloqueo PostgreSQL de la primera')
                self.assertFalse(segunda.done())
            finally:
                liberar.set()
            self.assertEqual(primera.result(timeout=10), 302)
            self.assertEqual(segunda.result(timeout=10), 302)

    def test_dos_reasignaciones_reales_serializadas_con_historial(self):
        self.ejecutar_conexiones_independientes()
        self.assertEqual(self.ticket.asignaciones.count(), 2)
        actual = self.ticket.asignaciones.get(activo=True)
        self.ticket.refresh_from_db()
        self.assertEqual(actual.tecnico, self.tecnico_b)
        self.assertEqual(actual.scheduled_at, self.ticket.scheduled_at)
        self.assertIsNotNone(self.ticket.asignaciones.get(activo=False).scheduled_at)
        self.assertEqual(TicketEvent.objects.count(), 2)

    def test_reenvios_identicos_concurrentes_no_duplican_asignacion(self):
        self.ejecutar_conexiones_independientes(mismo_tecnico=True)
        self.assertEqual(self.ticket.asignaciones.count(), 1)
        self.assertEqual(self.ticket.asignaciones.filter(activo=True).count(), 1)
        self.assertEqual(TicketEvent.objects.count(), 1)


class MigracionAsignacionesTests(TransactionTestCase):
    anterior = [('tickets', '0002_ticket_fotografia')]
    nueva = [('tickets', '0003_programacion_y_asignacion_vigente')]

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.anterior)
        apps = executor.loader.project_state(self.anterior).apps
        self.Asignacion = apps.get_model('tickets', 'TicketAssignment')
        self.Ticket = apps.get_model('tickets', 'Ticket')
        Usuario = apps.get_model('accounts', 'User')
        usuario = Usuario.objects.create(username='tecnico_migracion', roles='tecnico')
        area = apps.get_model('accounts', 'Area').objects.create(nombre='TI migración', codigo='TI')
        servicio = apps.get_model('core', 'Servicio').objects.create(nombre='Servicio migración', codigo='MIG')
        sala = apps.get_model('core', 'AreaProblema').objects.create(nombre='Sala migración', codigo='MIG')
        self.fecha = timezone.now().replace(microsecond=0)
        self.ticket = self.Ticket.objects.create(codigo_ticket='MIG-ASIGNACION', solicitante_id=usuario.pk,
            area_soporte_id=area.pk, servicio_id=servicio.pk, area_problema_id=sala.pk,
            descripcion='Datos existentes ficticios', scheduled_at=self.fecha)
        self.usuario_id = usuario.pk
        self.anterior_id = self.Asignacion.objects.create(ticket=self.ticket, tecnico_id=usuario.pk,
            asignado_por_id=usuario.pk, activo=False).pk
        self.vigente_id = self.Asignacion.objects.create(ticket=self.ticket, tecnico_id=usuario.pk,
            asignado_por_id=usuario.pk, activo=True).pk

    def tearDown(self):
        # Solo datos ficticios de esta prueba: permite restaurar el esquema final
        # después de probar el rechazo de duplicados en el esquema anterior.
        self.Asignacion.objects.filter(ticket_id=self.ticket.pk).exclude(pk=self.vigente_id).update(activo=False)
        MigrationExecutor(connection).migrate(self.nueva)
        # Los datos ficticios ya fueron comprobados; restaurar el esquema vigente.
        Ticket.objects.all().delete()
        MigrationExecutor(connection).migrate([('tickets', '0004_contador_diario_ticket')])
        super().tearDown()

    def test_migra_datos_existentes_sin_inventar_fechas_historicas(self):
        anteriores = list(self.Asignacion.objects.order_by('pk').values())
        AtencionTecnica.objects.create(ticket_id=self.ticket.pk, tecnico_id=self.usuario_id, diagnostico='Historia intacta')
        historia = list(AtencionTecnica.objects.values())
        sin_vigente = self.Ticket.objects.get(pk=self.ticket.pk)
        sin_vigente.pk = None
        sin_vigente.codigo_ticket = 'MIG-SIN-VIGENTE'
        sin_vigente.save()
        MigrationExecutor(connection).migrate(self.nueva)
        self.assertEqual(TicketAssignment.objects.get(pk=self.vigente_id).scheduled_at, self.fecha)
        self.assertIsNone(TicketAssignment.objects.get(pk=self.anterior_id).scheduled_at)
        for fila in anteriores:
            actual = TicketAssignment.objects.values().get(pk=fila['id'])
            actual.pop('scheduled_at')
            self.assertEqual(actual, fila)
        self.assertEqual(list(AtencionTecnica.objects.values()), historia)
        self.assertEqual(Ticket.objects.get(pk=sin_vigente.pk).scheduled_at, self.fecha)
        self.assertFalse(TicketAssignment.objects.filter(ticket_id=sin_vigente.pk).exists())

    def test_duplicados_detienen_migracion_sin_modificar_datos(self):
        self.Asignacion.objects.create(ticket=self.ticket, tecnico_id=self.usuario_id,
                                      asignado_por_id=self.usuario_id, activo=True)
        antes = list(self.Asignacion.objects.order_by('pk').values())
        with self.assertRaisesRegex(RuntimeError, 'vigentes duplicadas'):
            MigrationExecutor(connection).migrate(self.nueva)
        self.assertEqual(list(self.Asignacion.objects.order_by('pk').values()), antes)
        with connection.cursor() as cursor:
            columnas = [c.name for c in connection.introspection.get_table_description(cursor, 'tickets_ticketassignment')]
        self.assertNotIn('scheduled_at', columnas)

    def test_reversion_inicial_sin_historia_nueva_es_segura(self):
        MigrationExecutor(connection).migrate(self.nueva)
        MigrationExecutor(connection).migrate(self.anterior)
        self.assertEqual(self.Ticket.objects.get(pk=self.ticket.pk).scheduled_at, self.fecha)
        MigrationExecutor(connection).migrate(self.nueva)
        self.assertEqual(TicketAssignment.objects.get(pk=self.vigente_id).scheduled_at, self.fecha)

    def test_reversion_rechaza_perdida_de_historia_nueva(self):
        MigrationExecutor(connection).migrate(self.nueva)
        TicketAssignment.objects.filter(pk=self.vigente_id).update(activo=False)
        nueva = TicketAssignment.objects.create(ticket_id=self.ticket.pk, tecnico_id=self.usuario_id,
            asignado_por_id=self.usuario_id, scheduled_at=self.fecha + timedelta(days=1))
        Ticket.objects.filter(pk=self.ticket.pk).update(scheduled_at=nueva.scheduled_at)
        antes = list(TicketAssignment.objects.order_by('pk').values())
        with self.assertRaisesRegex(RuntimeError, 'reversión detenida'):
            MigrationExecutor(connection).migrate(self.anterior)
        self.assertEqual(list(TicketAssignment.objects.order_by('pk').values()), antes)
