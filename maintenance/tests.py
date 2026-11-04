"""AUD-002: autorización técnica y conservación de atenciones históricas."""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import Area, User
from core.models import Servicio, AreaProblema
from tickets.models import Ticket, TicketAssignment, TicketEvent
from tickets.permissions import (
    INICIAR_ATENCION, EDITAR_ATENCION, FINALIZAR_ATENCION, puede_operar_ticket,
)
from .models import AtencionTecnica, RevisionSupervisor


class AutorizacionTecnicoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.area = Area.objects.create(nombre='TI ficticia', codigo='TI')
        cls.solicitante = User.objects.create_user(username='solicitante', roles='solicitante')
        cls.supervisor = User.objects.create_user(username='supervisor', roles='supervisor')
        cls.supervisor.areas.add(cls.area)
        cls.tecnico_a = User.objects.create_user(username='tecnico_a', roles='tecnico')
        cls.tecnico_b = User.objects.create_user(username='tecnico_b', roles='tecnico')
        cls.tecnico_c = User.objects.create_user(username='tecnico_c', roles='tecnico')
        for tecnico in [cls.tecnico_a, cls.tecnico_b, cls.tecnico_c]:
            tecnico.areas.add(cls.area)
        servicio = Servicio.objects.create(nombre='Servicio ficticio', codigo='TEST')
        ubicacion = AreaProblema.objects.create(nombre='Sala ficticia', codigo='SALA')
        cls.ticket = Ticket.objects.create(
            codigo_ticket='AUD002-TEST', solicitante=cls.solicitante, servicio=servicio,
            area_problema=ubicacion, area_soporte=cls.area, descripcion='Falla ficticia',
            estado='asignada',
        )
        TicketAssignment.objects.create(
            ticket=cls.ticket, tecnico=cls.tecnico_a, asignado_por=cls.supervisor,
        )

    def url(self, accion):
        return reverse('maintenance:' + accion, args=[self.ticket.pk])

    def snapshot(self):
        return [list(model.objects.order_by('pk').values()) for model in (
            Ticket, TicketAssignment, AtencionTecnica, TicketEvent, RevisionSupervisor,
        )]

    def iniciar_a(self):
        self.client.force_login(self.tecnico_a)
        self.assertEqual(self.client.post(self.url('iniciar_atencion')).status_code, 302)
        return AtencionTecnica.objects.get(ticket=self.ticket, tecnico=self.tecnico_a)

    def reasignar_b(self):
        self.client.force_login(self.supervisor)
        response = self.client.post(reverse('tickets:asignar_tecnico', args=[self.ticket.pk]),
                                    {'tecnico': self.tecnico_b.pk})
        self.assertEqual(response.status_code, 302)
        self.ticket.refresh_from_db()

    def denegar_operaciones(self, usuario, acciones=None):
        self.client.force_login(usuario)
        acciones = acciones or ['iniciar_atencion', 'registrar_atencion', 'finalizar_atencion']
        for accion in acciones:
            for metodo in ['get', 'post']:
                with self.subTest(usuario=usuario.username, accion=accion, metodo=metodo):
                    antes = self.snapshot()
                    response = getattr(self.client, metodo)(self.url(accion),
                        {'diagnostico': 'Intento ajeno'} if metodo == 'post' else {})
                    # Las rutas de acción ahora rechazan GET antes del permiso
                    # de objeto. La edición conserva su formulario GET.
                    esperado = 405 if metodo == 'get' and accion != 'registrar_atencion' else 404
                    self.assertEqual(response.status_code, esperado)
                    self.assertEqual(self.snapshot(), antes)
                    self.assertNotContains(response, self.ticket.codigo_ticket, status_code=esperado)

    def test_a_asignado_puede_iniciar_su_atencion(self):
        atencion = self.iniciar_a()
        self.ticket.refresh_from_db()
        self.assertEqual(atencion.tecnico, self.tecnico_a)
        self.assertIsNotNone(atencion.work_started_at)
        self.assertEqual(self.ticket.estado, 'en_atencion')
        self.assertEqual(TicketEvent.objects.filter(tipo_accion='inicio_atencion').count(), 1)

    def test_reasignacion_conserva_registro_de_a_y_asignacion_anterior(self):
        atencion = self.iniciar_a()
        atencion.diagnostico = 'Diagnóstico histórico A'
        atencion.save()
        antes = AtencionTecnica.objects.values().get(pk=atencion.pk)
        self.reasignar_b()
        self.assertEqual(AtencionTecnica.objects.values().get(pk=atencion.pk), antes)
        self.assertEqual(self.ticket.asignaciones.count(), 2)
        self.assertFalse(self.ticket.asignaciones.get(tecnico=self.tecnico_a).activo)
        self.assertTrue(self.ticket.asignaciones.get(tecnico=self.tecnico_b).activo)

    def test_a_conserva_solo_consulta_historica_preexistente(self):
        atencion = self.iniciar_a()
        self.reasignar_b()
        self.client.force_login(self.tecnico_a)
        antes = self.snapshot()
        response = self.client.get(reverse('maintenance:lista_atenciones'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([a.pk for a in response.context['atenciones']], [atencion.pk])
        self.assertEqual(self.client.get(reverse('tickets:detalle_ticket', args=[self.ticket.pk])).status_code, 404)
        self.assertEqual(self.snapshot(), antes)

    def test_a_reasignado_no_edita_finaliza_ni_cambia_estado(self):
        self.iniciar_a()
        self.reasignar_b()
        self.denegar_operaciones(self.tecnico_a)
        # El estado ya permite editar a B: A debe seguir bloqueado por asignación.
        self.client.force_login(self.tecnico_b)
        self.assertEqual(self.client.post(self.url('iniciar_atencion')).status_code, 302)
        self.denegar_operaciones(self.tecnico_a)

    def test_b_inicia_registro_propio_sin_sobrescribir_a(self):
        anterior = self.iniciar_a()
        antes = AtencionTecnica.objects.values().get(pk=anterior.pk)
        self.reasignar_b()
        self.client.force_login(self.tecnico_b)
        self.assertEqual(self.client.post(self.url('iniciar_atencion')).status_code, 302)
        nueva = AtencionTecnica.objects.get(ticket=self.ticket, tecnico=self.tecnico_b)
        self.assertNotEqual(nueva.pk, anterior.pk)
        self.assertEqual(AtencionTecnica.objects.values().get(pk=anterior.pk), antes)
        self.assertEqual(AtencionTecnica.objects.filter(ticket=self.ticket).count(), 2)

    def test_b_no_utiliza_atencion_de_a_para_editar_o_finalizar(self):
        self.iniciar_a()
        self.reasignar_b()
        self.denegar_operaciones(self.tecnico_b, ['registrar_atencion', 'finalizar_atencion'])

    def test_identificadores_post_no_permiten_editar_atencion_de_a(self):
        anterior = self.iniciar_a()
        self.reasignar_b()
        self.client.force_login(self.tecnico_b)
        self.client.post(self.url('iniciar_atencion'))
        antes = AtencionTecnica.objects.values().get(pk=anterior.pk)
        response = self.client.post(self.url('registrar_atencion'), {
            'atencion_id': anterior.pk, 'tecnico': self.tecnico_a.pk,
            'diagnostico': 'Diagnóstico propio B', 'acciones_realizadas': 'Acción B',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AtencionTecnica.objects.values().get(pk=anterior.pk), antes)
        self.assertEqual(AtencionTecnica.objects.get(tecnico=self.tecnico_b).diagnostico, 'Diagnóstico propio B')

    def test_c_sin_asignacion_no_modifica(self):
        self.iniciar_a()
        self.denegar_operaciones(self.tecnico_c)

    def test_solicitante_supervisor_admin_no_operan_como_tecnico(self):
        self.iniciar_a()
        admin = User.objects.create_user(username='admin', roles='administrador')
        for usuario in [self.solicitante, self.supervisor, admin]:
            self.denegar_operaciones(usuario)

    def test_anonimo_no_opera(self):
        antes = self.snapshot()
        for accion in ['iniciar_atencion', 'registrar_atencion', 'finalizar_atencion']:
            for metodo in ['get', 'post']:
                response = getattr(self.client, metodo)(self.url(accion))
                self.assertEqual(response.status_code, 302)
                self.assertIn('/accounts/login/', response.url)
        self.assertEqual(self.snapshot(), antes)

    def test_ticket_cerrado_no_retrocede_por_ruta_antigua(self):
        self.iniciar_a()
        self.ticket.estado = 'cerrada_tecnicamente'
        self.ticket.closed_at = timezone.now()
        self.ticket.save()
        self.denegar_operaciones(self.tecnico_a)
        # Tampoco se habilita reapertura implícita si otra ruta cambió el estado.
        self.ticket.estado = 'asignada'
        self.ticket.save(update_fields=['estado'])
        self.denegar_operaciones(self.tecnico_a)

    def test_finalizacion_autorizada_y_bloqueo_posterior(self):
        atencion = self.iniciar_a()
        self.assertEqual(self.client.post(self.url('registrar_atencion'), {
            'diagnostico': 'Diagnóstico A', 'acciones_realizadas': 'Acción A',
        }).status_code, 302)
        self.assertEqual(self.client.post(self.url('finalizar_atencion')).status_code, 302)
        atencion.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertTrue(atencion.finalizado_por_tecnico)
        self.assertTrue(atencion.enviado_a_revision)
        self.assertIsNotNone(atencion.work_finished_at)
        self.assertEqual(self.ticket.estado, 'pendiente_validacion')
        self.assertIsNone(self.ticket.closed_at)
        self.denegar_operaciones(self.tecnico_a)

    def test_cualquier_marca_de_finalizacion_bloquea_edicion(self):
        atencion = self.iniciar_a()
        for campo, valor in [('finalizado_por_tecnico', True), ('enviado_a_revision', True),
                             ('work_finished_at', timezone.now())]:
            with self.subTest(campo=campo):
                AtencionTecnica.objects.filter(pk=atencion.pk).update(
                    finalizado_por_tecnico=False, enviado_a_revision=False, work_finished_at=None,
                )
                AtencionTecnica.objects.filter(pk=atencion.pk).update(**{campo: valor})
                self.denegar_operaciones(self.tecnico_a, ['registrar_atencion', 'finalizar_atencion'])
                self.ticket.estado = 'asignada'
                self.ticket.save(update_fields=['estado'])
                self.denegar_operaciones(self.tecnico_a, ['iniciar_atencion'])
                self.ticket.estado = 'en_atencion'
                self.ticket.save(update_fields=['estado'])

    def test_estado_no_admitido_y_atencion_no_iniciada_denegados(self):
        atencion = self.iniciar_a()
        for estado in ['registrada', 'revision', 'devuelta', 'pendiente_validacion', 'desconocido']:
            self.ticket.estado = estado
            self.ticket.save(update_fields=['estado'])
            self.denegar_operaciones(self.tecnico_a)
        self.ticket.estado = 'en_atencion'
        self.ticket.save(update_fields=['estado'])
        atencion.work_started_at = None
        atencion.save(update_fields=['work_started_at'])
        self.denegar_operaciones(self.tecnico_a, ['registrar_atencion', 'finalizar_atencion'])

    def test_propiedad_del_ticket_no_otorga_acciones_tras_reasignacion(self):
        self.iniciar_a()
        self.ticket.solicitante = self.tecnico_a
        self.ticket.save(update_fields=['solicitante'])
        self.reasignar_b()
        self.client.force_login(self.tecnico_a)
        response = self.client.get(reverse('tickets:detalle_ticket', args=[self.ticket.pk]))
        self.assertEqual(response.status_code, 200)
        for accion in ['iniciar_atencion', 'registrar_atencion', 'finalizar_atencion']:
            self.assertNotContains(response, self.url(accion))
        self.denegar_operaciones(self.tecnico_a)

    def test_botones_reflejan_permiso_y_no_solo_estado(self):
        self.client.force_login(self.tecnico_a)
        detalle = reverse('tickets:detalle_ticket', args=[self.ticket.pk])
        response = self.client.get(detalle)
        self.assertContains(response, self.url('iniciar_atencion'))
        self.iniciar_a()
        response = self.client.get(detalle)
        self.assertNotContains(response, self.url('iniciar_atencion'))
        self.assertContains(response, self.url('registrar_atencion'))
        self.assertContains(response, self.url('finalizar_atencion'))
        self.client.post(self.url('finalizar_atencion'))
        response = self.client.get(detalle)
        for accion in ['iniciar_atencion', 'registrar_atencion', 'finalizar_atencion']:
            self.assertNotContains(response, self.url(accion))

    def test_atenciones_propias_ambiguas_denegadas_sin_elegir_una(self):
        self.iniciar_a()
        AtencionTecnica.objects.create(ticket=self.ticket, tecnico=self.tecnico_a,
                                      work_started_at=timezone.now())
        self.denegar_operaciones(self.tecnico_a, ['registrar_atencion', 'finalizar_atencion'])
        self.ticket.estado = 'asignada'
        self.ticket.save(update_fields=['estado'])
        self.denegar_operaciones(self.tecnico_a, ['iniciar_atencion'])

    def test_politica_central_no_autoriza_sin_contexto_tecnico(self):
        for accion in [INICIAR_ATENCION, EDITAR_ATENCION, FINALIZAR_ATENCION]:
            self.assertFalse(puede_operar_ticket(self.tecnico_c, self.ticket, accion))
        self.assertTrue(puede_operar_ticket(self.tecnico_a, self.ticket, INICIAR_ATENCION))
        self.iniciar_a()
        self.assertTrue(puede_operar_ticket(self.tecnico_a, self.ticket, EDITAR_ATENCION))
        self.assertTrue(puede_operar_ticket(self.tecnico_a, self.ticket, FINALIZAR_ATENCION))
