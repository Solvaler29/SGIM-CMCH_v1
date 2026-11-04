"""Carga demo: PostgreSQL temporal, credenciales efímeras y almacenamiento aislado."""
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
import os
from pathlib import Path
import secrets
from threading import Event
from time import monotonic, sleep
import tempfile
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import connection, connections, IntegrityError
from django.test import TestCase, TransactionTestCase, override_settings

from accounts.models import Area, User
from core.models import Servicio, AreaProblema
from equipment.models import Equipment
from maintenance.models import AtencionTecnica, RevisionSupervisor
from .models import Ticket, TicketAssignment, TicketEvent, ContadorDiarioTicket


class DatosDemo:
    def setUp(self):
        super().setUp()
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.carpeta = Path(carpeta.name)
        contexto = override_settings(DEBUG=True, MEDIA_ROOT=carpeta.name,
                                     PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
        contexto.enable()
        self.addCleanup(contexto.disable)
        variables = patch.dict(os.environ, {'SGIM_ALLOW_DEMO': '1', 'SGIM_DEMO_PASSWORD': secrets.token_urlsafe(24)})
        variables.start()
        self.addCleanup(variables.stop)

    def ejecutar(self, *opciones):
        salida = StringIO()
        call_command('cargar_demo_sgim', *opciones, stdout=salida)
        return json.loads(salida.getvalue())

    def snapshot(self):
        modelos = (Area, User, User.areas.through, Servicio, AreaProblema, Equipment,
                   Ticket, TicketAssignment, AtencionTecnica, RevisionSupervisor, TicketEvent, ContadorDiarioTicket)
        return ([list(m.objects.order_by('pk').values()) for m in modelos],
                sorted(str(p.relative_to(self.carpeta)) for p in self.carpeta.rglob('*') if p.is_file()))


class DemoTests(DatosDemo, TestCase):
    def test_conjunto_completo_coherente(self):
        resumen = self.ejecutar()
        self.assertEqual(resumen['totales_demo'], dict(areas=3, servicios=8, ubicaciones=8, equipos=12,
            usuarios=32, tickets=15, asignaciones=10, intervenciones=7, revisiones=3, eventos=60))
        self.assertEqual(resumen['por_rol'], dict(administrador=1, supervisor=9, tecnico=12, solicitante=10))
        self.assertEqual(set(resumen['tickets_por_estado']), set(dict(Ticket.ESTADOS)))
        self.assertEqual(sorted(resumen['tickets_por_area'].values()), [5, 5, 5])
        self.assertEqual(Ticket.objects.values('codigo_ticket').distinct().count(), 15)
        for area in Area.objects.all():
            self.assertEqual(area.usuarios.filter(roles='supervisor').count(), 3)
            self.assertEqual(area.usuarios.filter(roles='tecnico').count(), 4)
        self.assertFalse(User.objects.filter(is_staff=True).exists())
        self.assertFalse(User.objects.filter(is_superuser=True).exists())
        for ticket in Ticket.objects.all():
            self.assertTrue(ticket.fotografia.storage.exists(ticket.fotografia.name))
            self.assertLess(ticket.fotografia.size, 50000)
            self.assertTrue(ticket.eventos.get(tipo_accion='registro').detalles.startswith('DEMO-WALTER-v1|'))
            if ticket.equipo:
                self.assertIn(ticket.servicio.nombre, ticket.equipo.ubicacion)

    def test_segunda_ejecucion_no_modifica_ni_duplica(self):
        self.ejecutar()
        antes = self.snapshot()
        resumen = self.ejecutar()
        self.assertEqual(resumen['creados'], {})
        self.assertEqual(resumen['reutilizados']['Ticket'], 15)
        self.assertEqual(self.snapshot(), antes)

    def test_reutiliza_cuatro_cuentas_locales_sin_cambiar_claves(self):
        area = Area.objects.create(nombre='Tecnologia de la Informacion', codigo='TI')
        cuentas = []
        for username, rol in [('admin_local', 'administrador'), ('supervisor_local', 'supervisor'),
                              ('tecnico_local', 'tecnico'), ('solicitante_local', 'solicitante')]:
            usuario = User.objects.create_user(username=username, roles=rol, last_name='Prueba local',
                                               password=secrets.token_urlsafe(24))
            if rol in ('supervisor', 'tecnico'):
                usuario.areas.add(area)
            cuentas.append((usuario.pk, usuario.password))
        resumen = self.ejecutar()
        self.assertEqual(resumen['creados']['User'], 28)
        self.assertEqual(resumen['reutilizados']['User'], 4)
        self.assertEqual(User.objects.count(), 32)
        self.assertEqual(Area.objects.get(pk=area.pk).nombre, 'Tecnologia de la Informacion')
        for pk, clave in cuentas:
            self.assertEqual(User.objects.get(pk=pk).password, clave)

    def test_verificar_y_listar_son_lectura_y_no_exponen_claves(self):
        self.ejecutar()
        antes = self.snapshot()
        with patch.dict(os.environ, {'SGIM_DEMO_PASSWORD': ''}):
            resumen = self.ejecutar('--verificar')
            listado = self.ejecutar('--listar')
        self.assertEqual(resumen['creados'], {})
        self.assertEqual(len(listado['usuarios']), 32)
        self.assertEqual(len(listado['tickets']), 15)
        self.assertNotIn(os.environ['SGIM_DEMO_PASSWORD'], json.dumps(listado))
        self.assertEqual(self.snapshot(), antes)

    def test_verificacion_de_conjunto_ausente_no_crea_datos(self):
        antes = self.snapshot()
        with self.assertRaises(CommandError):
            self.ejecutar('--verificar')
        self.assertEqual(self.snapshot(), antes)

    @override_settings(DEBUG=False)
    def test_bloquea_produccion(self):
        with self.assertRaisesRegex(CommandError, 'Carga bloqueada'):
            self.ejecutar()
        self.assertFalse(User.objects.exists())

    def test_bloquea_destino_remoto(self):
        with patch.dict(connection.settings_dict, {'HOST': 'servidor-remoto.example.invalid'}):
            with self.assertRaisesRegex(CommandError, 'Carga bloqueada'):
                self.ejecutar()
        self.assertFalse(User.objects.exists())

    def test_exige_autorizacion_local_explicita(self):
        with patch.dict(os.environ, {'SGIM_ALLOW_DEMO': '0'}):
            with self.assertRaisesRegex(CommandError, 'Carga bloqueada'):
                self.ejecutar()
        self.assertFalse(User.objects.exists())

    def test_exige_password_configurada_sin_escribir(self):
        with patch.dict(os.environ, {'SGIM_DEMO_PASSWORD': ''}):
            with self.assertRaisesRegex(CommandError, 'Configura SGIM_DEMO_PASSWORD'):
                self.ejecutar()
        self.assertFalse(Area.objects.exists())

    def test_cuenta_incompatible_aborta_sin_sobrescribir(self):
        User.objects.create_user(username='demo_tecnico_ti_01', roles='solicitante')
        antes = self.snapshot()
        with self.assertRaisesRegex(CommandError, 'incompatibles'):
            self.ejecutar()
        self.assertEqual(self.snapshot(), antes)

    def test_error_evento_revierte_todo_y_retira_solo_imagenes_nuevas(self):
        conservado = self.carpeta / 'preexistente.txt'
        conservado.write_text('Dato ficticio previo que no se debe eliminar.', encoding='utf-8')
        antes = self.snapshot()
        with patch.object(TicketEvent.objects, 'create', side_effect=IntegrityError('fallo ficticio')):
            with self.assertRaises(IntegrityError):
                self.ejecutar()
        self.assertEqual(self.snapshot(), antes)
        self.assertEqual(conservado.read_text(encoding='utf-8'), 'Dato ficticio previo que no se debe eliminar.')

    def test_marcador_duplicado_detiene_carga_sin_elegir_ticket(self):
        self.ejecutar()
        original = TicketEvent.objects.filter(tipo_accion='registro').order_by('pk').first()
        TicketEvent.objects.create(ticket=original.ticket, usuario=original.usuario,
                                   tipo_accion='registro', detalles=original.detalles)
        antes = self.snapshot()
        with self.assertRaisesRegex(CommandError, 'Marcador demo duplicado'):
            self.ejecutar()
        self.assertEqual(self.snapshot(), antes)

    def test_reutilizar_preserva_modificaciones_del_demo(self):
        self.ejecutar()
        ticket = Ticket.objects.filter(estado='registrada').first()
        Ticket.objects.filter(pk=ticket.pk).update(descripcion='DEMO: descripción modificada durante la presentación.')
        antes = self.snapshot()
        self.ejecutar()
        self.assertEqual(self.snapshot(), antes)

    def test_no_modifica_ticket_ni_usuario_ajenos_al_conjunto(self):
        area = Area.objects.create(nombre='Tecnologia de la Informacion', codigo='TI')
        servicio = Servicio.objects.create(nombre='Servicio previo ficticio', codigo='PREVIO')
        ubicacion = AreaProblema.objects.create(nombre='Ubicación previa ficticia', codigo='PREVIO')
        usuario = User.objects.create_user(username='previo_ficticio', roles='solicitante', password=secrets.token_urlsafe(24))
        ticket = Ticket.objects.create(solicitante=usuario, servicio=servicio, area_problema=ubicacion,
                                       area_soporte=area, descripcion='Registro ficticio ajeno al conjunto demo.')
        anteriores = [(modelo, pk, modelo.objects.values().get(pk=pk)) for modelo, pk in (
            (Ticket, ticket.pk), (User, usuario.pk), (Area, area.pk), (Servicio, servicio.pk), (AreaProblema, ubicacion.pk),
        )]
        self.ejecutar()
        for modelo, pk, anterior in anteriores:
            self.assertEqual(modelo.objects.values().get(pk=pk), anterior)
        self.assertFalse(ticket.eventos.exists())
        self.assertEqual(Ticket.objects.count(), 16)


class DemoConcurrenteTests(DatosDemo, TransactionTestCase):
    def test_dos_cargas_con_conexiones_independientes_no_duplican(self):
        Area.objects.create(nombre='Tecnologia de la Informacion', codigo='TI')
        retenido, liberar, segundo_listo = Event(), Event(), Event()
        pids = {}

        def trabajador(primero):
            conexion = connections['default']
            try:
                with conexion.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    pids[primero] = cursor.fetchone()[0]
                if not primero:
                    segundo_listo.set()

                def retener(execute, sql, params, many, context):
                    resultado = execute(sql, params, many, context)
                    if primero and 'FOR NO KEY UPDATE' in sql and '"accounts_area"' in sql:
                        retenido.set()
                        if not liberar.wait(20):
                            raise AssertionError('No se liberó el área de prueba')
                    return resultado

                with conexion.execute_wrapper(retener):
                    return self.ejecutar()
            finally:
                conexion.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            primero = executor.submit(trabajador, True)
            try:
                self.assertTrue(retenido.wait(15))
                segundo = executor.submit(trabajador, False)
                self.assertTrue(segundo_listo.wait(15))
                bloqueado = False
                limite = monotonic() + 15
                while monotonic() < limite:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_blocking_pids(%s)', [pids[False]])
                        bloqueado = pids[True] in cursor.fetchone()[0]
                    if bloqueado:
                        break
                    sleep(0.02)
                self.assertTrue(bloqueado)
            finally:
                liberar.set()
            uno, dos = primero.result(timeout=45), segundo.result(timeout=45)
        self.assertNotEqual(pids[True], pids[False])
        self.assertEqual(uno['creados']['Ticket'], 15)
        self.assertEqual(dos['creados'], {})
        self.assertEqual(Ticket.objects.count(), 15)
        self.assertEqual(User.objects.count(), 32)
