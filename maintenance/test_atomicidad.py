"""AUD-012: rollback y serialización real en PostgreSQL; solo datos ficticios."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

from django.db import connection, connections, IntegrityError, OperationalError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Area, User
from core.models import Servicio, AreaProblema
from tickets.models import Ticket, TicketAssignment, TicketEvent
from .models import AtencionTecnica, RevisionSupervisor


OPERACIONES = ('iniciar', 'editar', 'finalizar', 'aprobar', 'devolver', 'priorizar', 'redirigir')


class DatosAtomicidad:
    def setUp(self):
        super().setUp()
        self.area = Area.objects.create(nombre='TI ficticia', codigo='TI')
        self.otra_area = Area.objects.create(nombre='IC ficticia', codigo='IC')
        self.servicio = Servicio.objects.create(nombre='Servicio ficticio', codigo='A12')
        self.sala = AreaProblema.objects.create(nombre='Sala ficticia', codigo='A12')
        self.solicitante = User.objects.create_user(username='a12_solicitante', roles='solicitante')
        self.admin = User.objects.create_user(username='a12_admin', roles='administrador')
        self.supervisor = User.objects.create_user(username='a12_supervisor', roles='supervisor')
        self.supervisor.areas.add(self.area)
        self.tecnico = User.objects.create_user(username='a12_tecnico', roles='tecnico')
        self.otro_tecnico = User.objects.create_user(username='a12_tecnico_b', roles='tecnico')
        self.tecnico.areas.add(self.area)
        self.otro_tecnico.areas.add(self.area)
        self.numero = 0

    def preparar(self, operacion):
        self.numero += 1
        estado = ('en_atencion' if operacion in ('editar', 'finalizar') else
                  'pendiente_validacion' if operacion in ('aprobar', 'devolver') else 'asignada')
        ticket = Ticket.objects.create(
            codigo_ticket=f'A12-{self.numero}', solicitante=self.solicitante,
            servicio=self.servicio, area_problema=self.sala, area_soporte=self.area,
            descripcion='Incidencia ficticia', estado=estado,
        )
        TicketAssignment.objects.create(ticket=ticket, tecnico=self.tecnico, asignado_por=self.admin)
        if operacion in ('editar', 'finalizar', 'aprobar', 'devolver'):
            revision = operacion in ('aprobar', 'devolver')
            AtencionTecnica.objects.create(
                ticket=ticket, tecnico=self.tecnico, work_started_at=timezone.now(),
                work_finished_at=timezone.now() if revision else None,
                finalizado_por_tecnico=revision, enviado_a_revision=revision,
            )
        return ticket

    def solicitud(self, operacion, ticket):
        if operacion in ('crear_usuario', 'editar_usuario'):
            datos = dict(username='a12_concurrente', first_name='Nombre', last_name='Ficticio',
                         email='ficticio@example.invalid', roles='tecnico', areas=[self.otra_area.pk],
                         password1='Aud012-Ficticia#2026!', password2='Aud012-Ficticia#2026!', is_active='on')
            url = (reverse('accounts:registro') if operacion == 'crear_usuario' else
                   reverse('accounts:usuario_editar', args=[self.tecnico.pk]))
            return self.admin, url, datos
        tecnicas = dict(iniciar='iniciar_atencion', editar='registrar_atencion', finalizar='finalizar_atencion')
        if operacion in tecnicas:
            return self.tecnico, reverse('maintenance:' + tecnicas[operacion], args=[ticket.pk]), {
                'diagnostico': 'Diagnostico ficticio', 'acciones_realizadas': 'Accion ficticia',
            }
        if operacion in ('aprobar', 'devolver'):
            return self.supervisor, reverse('maintenance:revisar_atencion', args=[ticket.pk]), {
                'decision': 'aprobado' if operacion == 'aprobar' else 'devuelto',
                'justificacion': 'Revision ficticia',
            }
        if operacion == 'asignar':
            return self.supervisor, reverse('tickets:asignar_tecnico', args=[ticket.pk]), {
                'tecnico': self.otro_tecnico.pk,
            }
        nombre = 'priorizar_ticket' if operacion == 'priorizar' else 'redirigir_ticket'
        datos = {'prioridad': 'alta'} if operacion == 'priorizar' else {'area_soporte': self.otra_area.pk}
        return self.admin, reverse('tickets:' + nombre, args=[ticket.pk]), datos

    def post(self, operacion, ticket):
        usuario, url, datos = self.solicitud(operacion, ticket)
        self.client.force_login(usuario)
        return self.client.post(url, datos)

    def snapshot(self):
        return [list(modelo.objects.order_by('pk').values()) for modelo in (
            Ticket, TicketAssignment, AtencionTecnica, RevisionSupervisor, TicketEvent,
        )]


class AtomicidadOperacionesTests(DatosAtomicidad, TestCase):
    def test_operaciones_validas_confirman_todas_sus_escrituras(self):
        esperados = dict(iniciar='en_atencion', editar='en_atencion', finalizar='pendiente_validacion',
                         aprobar='cerrada_tecnicamente', devolver='devuelta', priorizar='asignada', redirigir='revision')
        for operacion in OPERACIONES:
            with self.subTest(operacion=operacion):
                ticket = self.preparar(operacion)
                self.assertEqual(self.post(operacion, ticket).status_code, 302)
                ticket.refresh_from_db()
                self.assertEqual(ticket.estado, esperados[operacion])
                self.assertEqual(ticket.eventos.count(), 1)
                if operacion in ('aprobar', 'devolver'):
                    self.assertEqual(RevisionSupervisor.objects.filter(atencion__ticket=ticket).count(), 1)
                    self.assertEqual(ticket.closed_at is not None, operacion == 'aprobar')
                elif operacion in ('iniciar', 'editar', 'finalizar'):
                    atencion = ticket.atenciones.get()
                    self.assertIsNotNone(atencion.work_started_at)
                    if operacion == 'editar':
                        self.assertEqual(atencion.diagnostico, 'Diagnostico ficticio')
                    if operacion == 'finalizar':
                        self.assertTrue(atencion.finalizado_por_tecnico and atencion.enviado_a_revision)
                        self.assertIsNotNone(atencion.work_finished_at)
                elif operacion == 'priorizar':
                    self.assertEqual(ticket.prioridad, 'alta')
                else:
                    self.assertEqual(ticket.area_soporte, self.otra_area)

    def test_error_evento_revierte_todas_las_operaciones(self):
        for operacion in OPERACIONES:
            with self.subTest(operacion=operacion):
                ticket = self.preparar(operacion)
                antes = self.snapshot()
                with patch('tickets.models.TicketEvent.objects.create', side_effect=IntegrityError('evento ficticio')):
                    with self.assertRaises(IntegrityError):
                        self.post(operacion, ticket)
                self.assertEqual(self.snapshot(), antes)

    def test_error_intermedio_revierte_atencion_o_revision(self):
        for operacion in ('iniciar', 'finalizar', 'aprobar', 'devolver'):
            with self.subTest(operacion=operacion):
                ticket = self.preparar(operacion)
                antes = self.snapshot()
                with patch.object(Ticket, 'save', side_effect=IntegrityError('estado ficticio')):
                    with self.assertRaises(IntegrityError):
                        self.post(operacion, ticket)
                self.assertEqual(self.snapshot(), antes)

    def test_error_antes_de_primera_escritura_no_cambia_datos(self):
        for operacion in OPERACIONES:
            with self.subTest(operacion=operacion):
                ticket = self.preparar(operacion)
                antes = self.snapshot()
                if operacion == 'iniciar':
                    objeto, metodo = AtencionTecnica.objects, 'create'
                elif operacion in ('editar', 'finalizar'):
                    objeto, metodo = AtencionTecnica, 'save'
                elif operacion in ('aprobar', 'devolver'):
                    objeto, metodo = RevisionSupervisor.objects, 'create'
                else:
                    objeto, metodo = Ticket, 'save'
                with patch.object(objeto, metodo, side_effect=IntegrityError('primera escritura ficticia')):
                    with self.assertRaises(IntegrityError):
                        self.post(operacion, ticket)
                self.assertEqual(self.snapshot(), antes)

    def test_no_autorizado_no_modifica_ninguna_operacion(self):
        self.client.force_login(self.solicitante)
        for operacion in OPERACIONES:
            ticket = self.preparar(operacion)
            _, url, datos = self.solicitud(operacion, ticket)
            antes = self.snapshot()
            self.assertEqual(self.client.post(url, datos).status_code, 404)
            self.assertEqual(self.snapshot(), antes)

    def test_repeticiones_no_duplican_historial_ni_fechas(self):
        for operacion in OPERACIONES:
            with self.subTest(operacion=operacion):
                ticket = self.preparar(operacion)
                self.assertEqual(self.post(operacion, ticket).status_code, 302)
                antes = self.snapshot()
                esperado = 404 if operacion in ('iniciar', 'finalizar') else 302
                self.assertEqual(self.post(operacion, ticket).status_code, esperado)
                self.assertEqual(self.snapshot(), antes)

    def test_estados_tecnicos_invalidos_no_escriben(self):
        for operacion in ('iniciar', 'editar', 'finalizar'):
            ticket = self.preparar(operacion)
            Ticket.objects.filter(pk=ticket.pk).update(estado='revision')
            antes = self.snapshot()
            self.assertEqual(self.post(operacion, ticket).status_code, 404)
            self.assertEqual(self.snapshot(), antes)

    def test_revision_invalida_ambigua_o_cerrada_no_escribe(self):
        ticket = self.preparar('aprobar')
        usuario, url, datos = self.solicitud('aprobar', ticket)
        self.client.force_login(usuario)
        antes = self.snapshot()
        self.assertEqual(self.client.post(url, {'decision': 'inexistente'}).status_code, 400)
        self.assertEqual(self.snapshot(), antes)
        self.assertEqual(self.client.post(url, datos).status_code, 302)
        antes = self.snapshot()
        self.assertEqual(self.client.post(url, {'decision': 'devuelto'}).status_code, 409)
        self.assertEqual(self.snapshot(), antes)
        ambiguo = self.preparar('aprobar')
        AtencionTecnica.objects.create(ticket=ambiguo, tecnico=self.otro_tecnico)
        antes = self.snapshot()
        self.assertEqual(self.post('aprobar', ambiguo).status_code, 404)
        self.assertEqual(self.snapshot(), antes)

    def test_conflicto_identificado_409_con_rollback(self):
        ticket = self.preparar('finalizar')
        antes = self.snapshot()
        causa = Exception('serializacion ficticia')
        causa.pgcode = '40001'
        error = OperationalError('serializacion ficticia')
        error.__cause__ = causa
        with patch('tickets.models.TicketEvent.objects.create', side_effect=error):
            self.assertEqual(self.post('finalizar', ticket).status_code, 409)
        self.assertEqual(self.snapshot(), antes)

    def test_redireccion_no_revierte_un_cierre_confirmado(self):
        ticket = self.preparar('aprobar')
        self.assertEqual(self.post('aprobar', ticket).status_code, 302)
        antes = self.snapshot()
        self.assertEqual(self.post('redirigir', ticket).status_code, 409)
        self.assertEqual(self.snapshot(), antes)

    def test_error_operacional_inesperado_no_se_oculta(self):
        ticket = self.preparar('finalizar')
        antes = self.snapshot()
        with patch('tickets.models.TicketEvent.objects.create', side_effect=OperationalError('fallo inesperado')):
            with self.assertRaises(OperationalError):
                self.post('finalizar', ticket)
        self.assertEqual(self.snapshot(), antes)


class CuentasAtomicasTests(DatosAtomicidad, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def datos_usuario(self):
        return dict(username='a12_nueva', first_name='Nombre', last_name='Ficticio',
                    email='ficticio@example.invalid', roles='tecnico', areas=[self.otra_area.pk],
                    password1='Aud012-Ficticia#2026!', password2='Aud012-Ficticia#2026!', is_active='on')

    def cuentas(self):
        return (list(User.objects.order_by('pk').values()),
                list(User.areas.through.objects.order_by('pk').values()))

    def test_creacion_valida_y_repetida(self):
        url = reverse('accounts:registro')
        self.assertEqual(self.client.post(url, self.datos_usuario()).status_code, 302)
        nueva = User.objects.get(username='a12_nueva')
        self.assertEqual(list(nueva.areas.all()), [self.otra_area])
        antes = self.cuentas()
        self.assertEqual(self.client.post(url, self.datos_usuario()).status_code, 200)
        self.assertEqual(self.cuentas(), antes)

    def test_edicion_valida_y_repetida(self):
        url = reverse('accounts:usuario_editar', args=[self.tecnico.pk])
        self.assertEqual(self.client.post(url, self.datos_usuario()).status_code, 302)
        self.tecnico.refresh_from_db()
        self.assertEqual(self.tecnico.first_name, 'Nombre')
        self.assertEqual(list(self.tecnico.areas.all()), [self.otra_area])
        antes = self.cuentas()
        self.assertEqual(self.client.post(url, self.datos_usuario()).status_code, 302)
        self.assertEqual(self.cuentas(), antes)

    def test_error_areas_revierte_usuario_y_relaciones(self):
        from accounts.forms import CustomUserCreationForm, UserEditForm
        for formulario, url in (
            (CustomUserCreationForm, reverse('accounts:registro')),
            (UserEditForm, reverse('accounts:usuario_editar', args=[self.tecnico.pk])),
        ):
            with self.subTest(formulario=formulario):
                antes = self.cuentas()
                original = formulario._save_m2m

                def fallar(instance):
                    original(instance)
                    raise IntegrityError('fallo ficticio despues de guardar areas')

                with patch.object(formulario, '_save_m2m', fallar):
                    with self.assertRaises(IntegrityError):
                        self.client.post(url, self.datos_usuario())
                self.assertEqual(self.cuentas(), antes)

    def test_datos_invalidos_o_actor_no_autorizado_no_escriben(self):
        for url in (reverse('accounts:registro'), reverse('accounts:usuario_editar', args=[self.tecnico.pk])):
            antes = self.cuentas()
            self.assertEqual(self.client.post(url, {'roles': 'invalido'}).status_code, 200)
            self.assertEqual(self.cuentas(), antes)
            self.client.force_login(self.solicitante)
            antes = self.cuentas()  # El login actualiza last_login legítimamente.
            self.assertEqual(self.client.post(url, self.datos_usuario()).status_code, 302)
            self.assertEqual(self.cuentas(), antes)
            self.client.force_login(self.admin)


class AtomicidadConcurrenteTests(DatosAtomicidad, TransactionTestCase):
    def ejecutar_concurrentes(self, ticket, primera, segunda, segundo_usuario=None):
        self.assertEqual(connection.vendor, 'postgresql')
        retenido, liberar, segundo_listo = Event(), Event(), Event()
        pids = {}

        def trabajador(operacion, primero):
            conexion = connections['default']
            try:
                usuario, url, datos = self.solicitud(operacion, ticket)
                if not primero and segundo_usuario is not None:
                    usuario = segundo_usuario
                if operacion == 'editar_usuario':
                    datos['first_name'] = 'Primero' if primero else 'Segundo'
                    datos['areas'] = [self.otra_area.pk if primero else self.area.pk]
                cliente = Client()
                cliente.force_login(usuario)
                with conexion.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    pids[primero] = cursor.fetchone()[0]
                if not primero:
                    segundo_listo.set()

                def retener(execute, sql, params, many, context):
                    resultado = execute(sql, params, many, context)
                    tabla = '"accounts_user"' if operacion in ('crear_usuario', 'editar_usuario') else '"tickets_ticket"'
                    escritura_o_bloqueo = ('INSERT INTO' in sql if operacion == 'crear_usuario' else 'FOR UPDATE' in sql)
                    if primero and escritura_o_bloqueo and tabla in sql:
                        retenido.set()
                        if not liberar.wait(20):
                            raise AssertionError('No se libero el ticket de prueba')
                    return resultado

                with conexion.execute_wrapper(retener):
                    return cliente.post(url, datos).status_code
            finally:
                conexion.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            uno = executor.submit(trabajador, primera, True)
            try:
                self.assertTrue(retenido.wait(15))
                dos = executor.submit(trabajador, segunda, False)
                self.assertTrue(segundo_listo.wait(15))
                bloqueo_real = False
                limite = monotonic() + 15
                while monotonic() < limite:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_blocking_pids(%s)', [pids[False]])
                        bloqueo_real = pids[True] in cursor.fetchone()[0]
                    if bloqueo_real:
                        break
                    sleep(0.02)
                self.assertTrue(bloqueo_real, 'Debe existir bloqueo real en PostgreSQL')
            finally:
                liberar.set()
            resultados = [uno.result(timeout=20), dos.result(timeout=20)]
        self.assertNotEqual(pids[True], pids[False])
        return resultados

    def test_doble_inicio_unica_atencion_y_evento(self):
        ticket = self.preparar('iniciar')
        self.assertEqual(self.ejecutar_concurrentes(ticket, 'iniciar', 'iniciar'), [302, 404])
        self.assertEqual(ticket.atenciones.count(), 1)
        self.assertEqual(ticket.eventos.count(), 1)

    def test_doble_finalizacion_unico_evento(self):
        ticket = self.preparar('finalizar')
        self.assertEqual(self.ejecutar_concurrentes(ticket, 'finalizar', 'finalizar'), [302, 404])
        self.assertEqual(ticket.eventos.count(), 1)

    def test_edicion_identica_concurrente_unico_evento(self):
        ticket = self.preparar('editar')
        self.assertEqual(self.ejecutar_concurrentes(ticket, 'editar', 'editar'), [302, 302])
        self.assertEqual(ticket.eventos.count(), 1)

    def test_revision_identica_concurrente_unica_revision(self):
        ticket = self.preparar('aprobar')
        self.assertEqual(self.ejecutar_concurrentes(ticket, 'aprobar', 'aprobar'), [302, 302])
        self.assertEqual(RevisionSupervisor.objects.count(), 1)
        self.assertEqual(ticket.eventos.count(), 1)

    def test_decisiones_opuestas_no_reabren_cierre(self):
        ticket = self.preparar('aprobar')
        self.assertEqual(self.ejecutar_concurrentes(ticket, 'aprobar', 'devolver'), [302, 409])
        ticket.refresh_from_db()
        self.assertEqual(ticket.estado, 'cerrada_tecnicamente')
        self.assertEqual(RevisionSupervisor.objects.count(), 1)

    def test_cierre_impide_redireccion_concurrente(self):
        ticket = self.preparar('aprobar')
        self.assertEqual(self.ejecutar_concurrentes(ticket, 'aprobar', 'redirigir'), [302, 409])
        ticket.refresh_from_db()
        self.assertEqual(ticket.estado, 'cerrada_tecnicamente')
        self.assertEqual(ticket.area_soporte, self.area)
        self.assertEqual(ticket.eventos.count(), 1)

    def test_prioridad_identica_unico_evento(self):
        ticket = self.preparar('priorizar')
        self.assertEqual(self.ejecutar_concurrentes(ticket, 'priorizar', 'priorizar'), [302, 302])
        self.assertEqual(ticket.eventos.count(), 1)

    def test_redireccion_identica_unico_evento(self):
        ticket = self.preparar('redirigir')
        self.assertEqual(self.ejecutar_concurrentes(ticket, 'redirigir', 'redirigir'), [302, 302])
        self.assertEqual(ticket.eventos.count(), 1)

    def test_redireccion_revalida_alcance_del_supervisor_en_espera(self):
        ticket = self.preparar('redirigir')
        self.assertEqual(self.ejecutar_concurrentes(ticket, 'redirigir', 'priorizar', self.supervisor), [302, 404])
        ticket.refresh_from_db()
        self.assertEqual(ticket.prioridad, 'media')
        self.assertEqual(ticket.eventos.count(), 1)

    def test_reasignacion_revalida_tecnico_que_esperaba_iniciar(self):
        ticket = self.preparar('iniciar')
        self.assertEqual(self.ejecutar_concurrentes(ticket, 'asignar', 'iniciar'), [302, 404])
        self.assertFalse(ticket.atenciones.exists())
        self.assertEqual(ticket.asignaciones.get(activo=True).tecnico, self.otro_tecnico)

    def test_inicio_y_reasignacion_conservan_intervencion_historica(self):
        ticket = self.preparar('iniciar')
        self.assertEqual(self.ejecutar_concurrentes(ticket, 'iniciar', 'asignar'), [302, 302])
        self.assertEqual(ticket.atenciones.get().tecnico, self.tecnico)
        self.assertEqual(ticket.asignaciones.get(activo=True).tecnico, self.otro_tecnico)
        self.assertEqual(ticket.asignaciones.count(), 2)
        self.assertEqual(ticket.eventos.count(), 2)

    def test_finalizacion_impide_edicion_que_esperaba(self):
        ticket = self.preparar('finalizar')
        self.assertEqual(self.ejecutar_concurrentes(ticket, 'finalizar', 'editar'), [302, 404])
        self.assertEqual(ticket.atenciones.get().diagnostico, '')
        self.assertEqual(ticket.eventos.count(), 1)

    def test_edicion_cuenta_serializa_datos_y_areas(self):
        self.assertEqual(self.ejecutar_concurrentes(None, 'editar_usuario', 'editar_usuario'), [302, 302])
        self.tecnico.refresh_from_db()
        self.assertEqual(self.tecnico.first_name, 'Segundo')
        self.assertEqual(list(self.tecnico.areas.all()), [self.area])

    def test_creacion_cuenta_concurrente_conflicto_controlado(self):
        self.assertEqual(self.ejecutar_concurrentes(None, 'crear_usuario', 'crear_usuario'), [302, 400])
        self.assertEqual(User.objects.filter(username='a12_concurrente').count(), 1)
        self.assertEqual(list(User.objects.get(username='a12_concurrente').areas.all()), [self.otra_area])
