"""Regresiones AUD-001. Django ejecuta estos datos en una base de pruebas."""
from django.contrib.auth.models import AnonymousUser
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import Area, User
from core.models import Servicio, AreaProblema
from maintenance.models import AtencionTecnica, RevisionSupervisor
from .models import Ticket, TicketAssignment, TicketEvent
from .permissions import (
    CONSULTAR, CLASIFICAR, REDIRIGIR, ASIGNAR_TECNICO, REVISAR_ATENCION,
    ACCIONES_GESTION, puede_operar_ticket, tickets_para_usuario,
)


class AutorizacionPorAreaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ti = Area.objects.create(nombre='TI prueba', codigo='TI')
        cls.ic = Area.objects.create(nombre='IC prueba', codigo='IC')
        cls.man = Area.objects.create(nombre='Mantenimiento prueba', codigo='MAN')
        cls.servicio = Servicio.objects.create(nombre='Servicio ficticio', codigo='TEST')
        cls.ubicacion = AreaProblema.objects.create(nombre='Sala ficticia', codigo='SALA')

        def usuario(nombre, rol, *areas, **extra):
            u = User.objects.create_user(username=nombre, roles=rol, **extra)
            u.areas.set(areas)
            return u

        cls.solicitante = usuario('solicitante', 'solicitante')
        cls.otro_solicitante = usuario('otro', 'solicitante')
        cls.supervisor = usuario('supervisor_ti', 'supervisor', cls.ti)
        cls.multiarea = usuario('supervisor_multi', 'supervisor', cls.ti, cls.ic)
        cls.sin_area = usuario('supervisor_sin_area', 'supervisor')
        cls.admin = usuario('admin_operativo', 'administrador')
        cls.staff = usuario('staff_solicitante', 'solicitante', is_staff=True, is_superuser=True)
        cls.tecnico = usuario('tecnico_ti', 'tecnico', cls.ti)
        cls.tecnico_ic = usuario('tecnico_ic', 'tecnico', cls.ic)

        def ticket(codigo, area, solicitante=None):
            return Ticket.objects.create(
                codigo_ticket=codigo, solicitante=solicitante or cls.solicitante,
                servicio=cls.servicio, area_problema=cls.ubicacion,
                area_soporte=area, descripcion='Incidencia ficticia ' + codigo,
                estado='pendiente_validacion',
            )

        cls.ticket_ti = ticket('TEST-TI', cls.ti)
        cls.ticket_ic = ticket('TEST-IC', cls.ic)
        cls.ticket_man = ticket('TEST-MAN', cls.man, cls.otro_solicitante)
        cls.propio_fuera_area = ticket('TEST-PROPIO', cls.ic, cls.supervisor)
        for t, tecnico in [(cls.ticket_ti, cls.tecnico), (cls.ticket_ic, cls.tecnico_ic)]:
            TicketAssignment.objects.create(ticket=t, tecnico=tecnico, asignado_por=cls.admin)
            AtencionTecnica.objects.create(ticket=t, tecnico=tecnico, diagnostico='Prueba')

    def operaciones(self, ticket):
        return [
            (reverse('tickets:priorizar_ticket', args=[ticket.pk]), {'prioridad': 'alta'}),
            (reverse('tickets:redirigir_ticket', args=[ticket.pk]), {'area_soporte': self.ti.pk}),
            (reverse('tickets:asignar_tecnico', args=[ticket.pk]), {'tecnico': self.tecnico_ic.pk}),
            (reverse('maintenance:revisar_atencion', args=[ticket.pk]),
             {'decision': 'aprobado', 'justificacion': 'Prueba de autorización'}),
        ]

    def snapshot(self):
        return [list(model.objects.order_by('pk').values()) for model in (
            Ticket, TicketAssignment, AtencionTecnica, TicketEvent, RevisionSupervisor,
        )]

    def comprobar_denegacion(self, ticket, status=404):
        for url, datos in self.operaciones(ticket):
            for metodo in ['get', 'post']:
                with self.subTest(url=url, metodo=metodo):
                    antes = self.snapshot()
                    respuesta = getattr(self.client, metodo)(url, datos if metodo == 'post' else {})
                    self.assertEqual(respuesta.status_code, status)
                    self.assertEqual(self.snapshot(), antes)
                    self.assertNotContains(respuesta, ticket.codigo_ticket, status_code=status)

    def test_supervisor_consulta_su_area(self):
        self.client.force_login(self.supervisor)
        self.assertEqual(self.client.get(reverse('tickets:detalle_ticket', args=[self.ticket_ti.pk])).status_code, 200)
        self.assertTrue(self.supervisor.puede_ver_ticket(self.ticket_ti))
        self.assertTrue(self.supervisor.puede_gestionar_area(self.ti))

    def test_supervisor_no_consulta_area_ajena(self):
        self.client.force_login(self.supervisor)
        url = reverse('tickets:detalle_ticket', args=[self.ticket_ic.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, self.ticket_ic.codigo_ticket, status_code=404)

    def test_cuatro_operaciones_ajenas_denegadas_sin_escrituras(self):
        self.client.force_login(self.supervisor)
        self.comprobar_denegacion(self.ticket_ic)

    def test_objetos_inexistentes_y_ajenos_responden_igual(self):
        self.client.force_login(self.supervisor)
        for url, datos in self.operaciones(self.ticket_ic):
            inexistente = url.replace(f'/{self.ticket_ic.pk}/', '/999999/')
            self.assertEqual(self.client.post(url, datos).status_code, 404)
            self.assertEqual(self.client.post(inexistente, datos).status_code, 404)

    def test_supervisor_conserva_operaciones_de_su_area(self):
        self.client.force_login(self.supervisor)
        for url, _ in self.operaciones(self.ticket_ti):
            self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(reverse('tickets:priorizar_ticket', args=[self.ticket_ti.pk]), {'prioridad': 'alta'})
        self.ticket_ti.refresh_from_db()
        self.assertEqual(self.ticket_ti.prioridad, 'alta')
        self.client.post(reverse('tickets:asignar_tecnico', args=[self.ticket_ti.pk]), {'tecnico': self.tecnico.pk})
        self.assertEqual(self.ticket_ti.asignaciones.filter(activo=True).get().tecnico, self.tecnico)
        response = self.client.post(reverse('maintenance:revisar_atencion', args=[self.ticket_ti.pk]),
                                    {'decision': 'aprobado', 'justificacion': 'Validación ficticia'})
        self.assertEqual(response.status_code, 302)
        self.ticket_ti.refresh_from_db()
        self.assertEqual(self.ticket_ti.estado, 'cerrada_tecnicamente')
        self.assertIsNotNone(self.ticket_ti.closed_at)
        self.assertEqual(RevisionSupervisor.objects.count(), 1)

    def test_redireccion_autorizada_actualiza_alcance_actual(self):
        self.client.force_login(self.supervisor)
        response = self.client.post(reverse('tickets:redirigir_ticket', args=[self.ticket_ti.pk]),
                                    {'area_soporte': self.ic.pk})
        self.assertEqual(response.status_code, 302)
        self.ticket_ti.refresh_from_db()
        self.assertEqual(self.ticket_ti.area_soporte, self.ic)
        self.assertEqual(TicketEvent.objects.filter(tipo_accion='redireccion').count(), 1)
        self.comprobar_denegacion(self.ticket_ti)

    def test_administrador_operativo_global_sin_areas(self):
        self.client.force_login(self.admin)
        for accion in [CONSULTAR, *ACCIONES_GESTION]:
            self.assertTrue(puede_operar_ticket(self.admin, self.ticket_ic, accion))
        for url, datos in self.operaciones(self.ticket_ic):
            self.assertEqual(self.client.get(url).status_code, 200)
            if url == reverse('tickets:asignar_tecnico', args=[self.ticket_ic.pk]):
                # La operación anterior redirigió el ticket a TI.
                datos = {'tecnico': self.tecnico.pk}
            self.assertEqual(self.client.post(url, datos).status_code, 302)
        self.ticket_ic.refresh_from_db()
        self.assertEqual(self.ticket_ic.prioridad, 'alta')
        self.assertEqual(self.ticket_ic.area_soporte, self.ti)
        self.assertEqual(self.ticket_ic.estado, 'cerrada_tecnicamente')

    def test_anonimo_no_accede_ni_modifica(self):
        urls = [reverse('tickets:detalle_ticket', args=[self.ticket_ic.pk]),
                reverse('tickets:lista_tickets'), reverse('maintenance:lista_atenciones')]
        urls += [url for url, _ in self.operaciones(self.ticket_ic)]
        antes = self.snapshot()
        for url in urls:
            for metodo in ['get', 'post']:
                response = getattr(self.client, metodo)(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn('/accounts/login/', response.url)
        self.assertEqual(self.snapshot(), antes)
        self.assertFalse(puede_operar_ticket(AnonymousUser(), self.ticket_ti))

    def test_supervisor_multiarea_sin_acceso_adicional(self):
        self.client.force_login(self.multiarea)
        for ticket in [self.ticket_ti, self.ticket_ic]:
            self.assertEqual(self.client.get(reverse('tickets:detalle_ticket', args=[ticket.pk])).status_code, 200)
            for accion in ACCIONES_GESTION:
                self.assertTrue(puede_operar_ticket(self.multiarea, ticket, accion))
            for url, _ in self.operaciones(ticket):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.comprobar_denegacion(self.ticket_man)

    def test_listados_y_dashboard_supervisor_limitados(self):
        self.client.force_login(self.supervisor)
        for name in ['tickets:lista_tickets', 'core:dashboard']:
            response = self.client.get(reverse(name))
            self.assertSetEqual({t.pk for t in response.context['tickets']},
                                {self.ticket_ti.pk, self.propio_fuera_area.pk})
            self.assertNotContains(response, self.ticket_ic.codigo_ticket)
            self.assertNotContains(response, self.ticket_man.codigo_ticket)
        self.assertEqual(self.client.get(reverse('core:dashboard')).context['total_tickets'], 2)
        for name in ['maintenance:lista_atenciones', 'maintenance:atenciones_alias']:
            response = self.client.get(reverse(name))
            self.assertEqual([a.ticket_id for a in response.context['atenciones']], [self.ticket_ti.pk])
            self.assertNotContains(response, self.ticket_ic.codigo_ticket)

    def test_multiarea_y_admin_listan_atenciones_autorizadas(self):
        for user in [self.multiarea, self.admin]:
            self.client.force_login(user)
            response = self.client.get(reverse('maintenance:lista_atenciones'))
            self.assertSetEqual({a.ticket_id for a in response.context['atenciones']},
                                {self.ticket_ti.pk, self.ticket_ic.pk})

    def test_propietario_supervisor_fuera_area_solo_consulta(self):
        self.client.force_login(self.supervisor)
        response = self.client.get(reverse('tickets:detalle_ticket', args=[self.propio_fuera_area.pk]))
        self.assertEqual(response.status_code, 200)
        for name in ['tickets:asignar_tecnico', 'tickets:priorizar_ticket', 'tickets:redirigir_ticket',
                     'maintenance:revisar_atencion']:
            self.assertNotContains(response, reverse(name, args=[self.propio_fuera_area.pk]))
        self.comprobar_denegacion(self.propio_fuera_area)

    def test_acciones_visibles_solo_en_area_gestionable(self):
        self.client.force_login(self.supervisor)
        response = self.client.get(reverse('tickets:detalle_ticket', args=[self.ticket_ti.pk]))
        for name in ['tickets:asignar_tecnico', 'tickets:priorizar_ticket', 'tickets:redirigir_ticket',
                     'maintenance:revisar_atencion']:
            self.assertContains(response, reverse(name, args=[self.ticket_ti.pk]))

    def test_solicitante_conserva_acceso_propio_sin_gestion(self):
        self.client.force_login(self.solicitante)
        self.assertEqual(self.client.get(reverse('tickets:detalle_ticket', args=[self.ticket_ic.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('tickets:detalle_ticket', args=[self.ticket_man.pk])).status_code, 404)
        self.comprobar_denegacion(self.ticket_ic)

    def test_tecnico_conserva_asignaciones_y_atenciones_propias(self):
        # Una edición legítima necesita atención iniciada y ticket en atención.
        self.ticket_ti.estado = 'en_atencion'
        self.ticket_ti.save(update_fields=['estado'])
        self.ticket_ti.atenciones.update(work_started_at=timezone.now())
        self.client.force_login(self.tecnico)
        self.assertEqual(self.client.get(reverse('tickets:detalle_ticket', args=[self.ticket_ti.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('tickets:detalle_ticket', args=[self.ticket_ic.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('maintenance:registrar_atencion', args=[self.ticket_ti.pk])).status_code, 200)
        response = self.client.get(reverse('maintenance:lista_atenciones'))
        self.assertEqual([a.ticket_id for a in response.context['atenciones']], [self.ticket_ti.pk])
        self.comprobar_denegacion(self.ticket_ti)

    def test_staff_superuser_no_otorga_rol_operativo_global(self):
        self.client.force_login(self.staff)
        self.comprobar_denegacion(self.ticket_ic)
        self.assertEqual(list(tickets_para_usuario(self.staff)), [])

    def test_sin_area_y_acciones_desconocidas_denegados(self):
        self.client.force_login(self.sin_area)
        self.comprobar_denegacion(self.ticket_ti)
        self.assertFalse(puede_operar_ticket(self.admin, self.ticket_ti, 'permiso_inexistente'))
        self.assertFalse(self.sin_area.puede_gestionar_area(self.ti))

    def test_post_conserva_proteccion_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.supervisor)
        antes = self.snapshot()
        response = client.post(reverse('tickets:priorizar_ticket', args=[self.ticket_ti.pk]), {'prioridad': 'alta'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.snapshot(), antes)
