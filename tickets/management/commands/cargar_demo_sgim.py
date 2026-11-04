"""Carga local idempotente. No cambia reglas, modelos ni contraseñas existentes."""
from collections import Counter
from datetime import timedelta
from io import BytesIO
import json
import os
import unicodedata

from PIL import Image, ImageDraw
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.http import HttpRequest
from django.utils import timezone

from accounts.models import Area, User
from core.models import Servicio, AreaProblema
from equipment.models import Equipment
from maintenance.models import AtencionTecnica, RevisionSupervisor
from maintenance import views as mantenimiento
from tickets import views as incidencias
from tickets.demo_data import AREAS, SERVICIOS, EQUIPOS, CASOS
from tickets.models import Ticket, TicketAssignment, TicketEvent
from tickets.forms import TicketForm
from tickets.permissions import puede_registrar_incidencia


MARCA = 'DEMO-WALTER-v1'


def normalizar(nombre):
    texto = unicodedata.normalize('NFKD', nombre).encode('ascii', 'ignore').decode().lower()
    return ''.join(letra for letra in texto if letra.isalnum())


class Command(BaseCommand):
    help = 'Prepara datos ficticios Walter v1, únicamente en PostgreSQL local de desarrollo.'

    def add_arguments(self, parser):
        parser.add_argument('--verificar', action='store_true', help='Solo comprobar; no crear ni reparar registros.')
        parser.add_argument('--listar', action='store_true', help='Solo comprobar y listar identificadores demo; nunca contraseñas.')

    def comprobar_destino(self):
        db = connection.settings_dict
        nombre = str(db['NAME'])
        if (not settings.DEBUG or connection.vendor != 'postgresql'
                or db['HOST'] not in ('localhost', '127.0.0.1', '::1')
                or str(db['PORT']) != '5433'
                or not (nombre == 'sgim_cmch' or nombre.startswith('test_sgim_'))
                or os.environ.get('SGIM_ALLOW_DEMO') != '1'):
            raise CommandError('Carga bloqueada: exige DEBUG, PostgreSQL local autorizado y SGIM_ALLOW_DEMO=1.')

    def handle(self, *args, **options):
        self.comprobar_destino()
        self.solo_lectura = options['verificar'] or options['listar']
        self.password = os.environ.get('SGIM_DEMO_PASSWORD', '')
        if not self.solo_lectura:
            if not self.password:
                raise CommandError('Configura SGIM_DEMO_PASSWORD localmente; no se imprimirá ni se guardará en el repositorio.')
            try:
                validate_password(self.password)
            except ValidationError:
                raise CommandError('SGIM_DEMO_PASSWORD no satisface los validadores de contraseña.') from None
        self.nuevos = Counter()
        self.archivos = []
        self.usuarios = []
        self.tickets = []
        confirmado = False
        try:
            with transaction.atomic():
                # Una fila estable serializa dos cargas demo. NO KEY UPDATE permite
                # las referencias FK normales y evita invertir los bloqueos del contador.
                ti = self.area('TI')
                if not self.solo_lectura:
                    Area.objects.select_for_update(no_key=True).get(pk=ti.pk)
                self.areas = {'TI': ti, 'IC': self.area('IC'), 'MAN': self.area('MAN')}
                self.preparar_catalogos()
                self.preparar_usuarios()
                self.preparar_tickets()
                self.verificar()
            confirmado = True
        finally:
            if not confirmado:
                # Solo archivos nuevos de esta ejecución; jamás rutas preexistentes.
                for storage, nombre in self.archivos:
                    try:
                        storage.delete(nombre)
                    except OSError:
                        self.stderr.write('No se pudo retirar una imagen demo nueva tras rollback; revisar almacenamiento.')
        resultado = self.resumen()
        if options['listar']:
            resultado['usuarios'] = self.usuarios
            resultado['tickets'] = list(Ticket.objects.filter(pk__in=self.tickets).order_by('pk').values(
                'id', 'codigo_ticket', 'estado', 'area_soporte__codigo',
            ))
        self.stdout.write(json.dumps(resultado, ensure_ascii=False, indent=2))

    def obtener(self, modelo, consulta, datos):
        objeto = modelo.objects.filter(**consulta).first()
        if objeto is not None:
            return objeto
        if self.solo_lectura:
            raise CommandError(f'Falta un registro demo de {modelo.__name__}: {consulta}.')
        objeto, creado = modelo.objects.get_or_create(**consulta, defaults=datos)
        if creado:
            self.nuevos[modelo.__name__] += 1
        return objeto

    def area(self, codigo):
        nombre, alias = AREAS[codigo]
        area = Area.objects.filter(codigo__iexact=codigo).first()
        if area is None:
            candidatas = [a for a in Area.objects.all() if normalizar(a.nombre) in alias]
            if len(candidatas) > 1:
                raise CommandError(f'Catálogo ambiguo para el área {codigo}; no se modificó.')
            area = candidatas[0] if candidatas else None
        if area is None:
            area = self.obtener(Area, {'codigo': codigo}, {'nombre': nombre})
        if not area.activa:
            raise CommandError(f'El área {codigo} está inactiva; no se reactivará automáticamente.')
        return area

    def preparar_catalogos(self):
        self.servicios, self.ubicaciones, self.equipos = [], [], {}
        for i, nombre in enumerate(SERVICIOS, 1):
            servicio = Servicio.objects.filter(nombre__iexact=nombre).first()
            if servicio is None:
                servicio = self.obtener(Servicio, {'codigo': f'DEMO-SRV-{i:02d}'}, {
                    'nombre': f'DEMO - {nombre}', 'descripcion': f'{MARCA}: servicio ficticio, no validado institucionalmente.',
                })
            if not servicio.activo:
                raise CommandError('Existe un servicio demo inactivo; se conserva sin modificar.')
            self.servicios.append(servicio)
            ubicacion = self.obtener(AreaProblema, {'codigo': f'DEMO-UBI-{i:02d}'}, {
                'nombre': f'DEMO - Sala {i:02d} ({nombre})', 'descripcion': f'{MARCA}: ubicación ficticia.',
            })
            if not ubicacion.activo:
                raise CommandError('Existe una ubicación demo inactiva; se conserva sin modificar.')
            self.ubicaciones.append(ubicacion)
        for area_i, (codigo, nombres) in enumerate(EQUIPOS.items()):
            self.equipos[codigo] = []
            for i, nombre in enumerate(nombres, 1):
                servicio = self.servicios[(area_i * 4 + i - 1) % len(self.servicios)]
                equipo = self.obtener(Equipment, {'codigo_equipo': f'DEMO-W-{codigo}-{i:02d}'}, {
                    'nombre': f'DEMO - {nombre}', 'qr_identifier': f'QR-DEMO-W-{codigo}-{i:02d}',
                    'marca': 'Simulada DEMO', 'modelo': f'Simulador {i:02d}',
                    'numero_serie': f'DEMO-{codigo}-{i:02d}',
                    'ubicacion': f'{servicio.nombre} / {self.areas[codigo].nombre}',
                    'estado_referencia': 'DEMO: equipo ficticio para pruebas',
                })
                self.equipos[codigo].append(equipo)

    def usuario(self, username, rol, area=None, reutilizable=None):
        usuario = User.objects.filter(username=username).first()
        if usuario is None and reutilizable:
            candidato = User.objects.filter(username=reutilizable).first()
            if candidato is not None:
                marcador_local = candidato.last_name in ('Prueba local', 'Local')
                if not marcador_local:
                    raise CommandError(f'La cuenta {reutilizable} no está identificada como prueba local.')
                usuario = candidato
        if usuario is None:
            if self.solo_lectura:
                raise CommandError(f'Falta la cuenta demo {username}.')
            usuario = User.objects.create_user(
                username=username, password=self.password, roles=rol,
                first_name='DEMO', last_name=username.removeprefix('demo_').replace('_', ' '),
                email=f'{username}@example.invalid', is_staff=False, is_superuser=False,
            )
            if area:
                usuario.areas.add(area)
            self.nuevos['User'] += 1
        if usuario.roles != rol or not usuario.is_active:
            raise CommandError(f'La cuenta {usuario.username} tiene rol o activación incompatibles; no se modificó.')
        if area and set(usuario.areas.values_list('pk', flat=True)) != {area.pk}:
            raise CommandError(f'Áreas incompatibles en {usuario.username}; no se modificaron.')
        self.usuarios.append({'username': usuario.username, 'rol': rol, 'area': area.codigo if area else None})
        return usuario

    def preparar_usuarios(self):
        self.administrador = self.usuario('demo_admin', 'administrador', reutilizable='admin_local')
        self.supervisores, self.tecnicos = {}, {}
        for codigo, area in self.areas.items():
            self.supervisores[codigo] = [self.usuario(
                f'demo_supervisor_{codigo.lower()}_{i:02d}', 'supervisor', area,
                'supervisor_local' if codigo == 'TI' and i == 1 else None,
            ) for i in range(1, 4)]
            self.tecnicos[codigo] = [self.usuario(
                f'demo_tecnico_{codigo.lower()}_{i:02d}', 'tecnico', area,
                'tecnico_local' if codigo == 'TI' and i == 1 else None,
            ) for i in range(1, 5)]
        self.solicitantes = [self.usuario(
            f'demo_solicitante_{i:02d}', 'solicitante', reutilizable='solicitante_local' if i == 1 else None,
        ) for i in range(1, 11)]

    def ejecutar(self, vista, usuario, parametros, datos=None, archivos=None):
        # Invocación interna autorizada, sin cambiar middleware ni CSRF web.
        request = HttpRequest()
        request.method = 'POST'
        request.user = usuario
        request.POST.update(datos or {})
        request.FILES.update(archivos or {})
        request.session = {}
        request._messages = FallbackStorage(request)
        response = vista(request, **parametros)
        if response.status_code != 302:
            raise CommandError(f'La operación demo {vista.__name__} fue rechazada (HTTP {response.status_code}).')
        return response

    def imagen(self, clave):
        imagen = Image.new('RGB', (720, 420), '#fff8e1')
        dibujo = ImageDraw.Draw(imagen)
        dibujo.rounded_rectangle((12, 12, 708, 408), radius=20, outline='#c62828', width=5)
        dibujo.text((40, 55), 'DEMO SGIM - DATOS COMPLETAMENTE FICTICIOS', fill='#b71c1c')
        dibujo.text((40, 110), clave, fill='#333333')
        dibujo.rectangle((240, 170, 480, 310), fill='#eeeeee', outline='#777777', width=3)
        dibujo.text((40, 355), 'Sin pacientes, personas ni instalaciones reales.', fill='#555555')
        salida = BytesIO()
        imagen.save(salida, format='PNG', optimize=True)
        return salida.getvalue()

    def preparar_tickets(self):
        numero = 0
        for codigo, casos in CASOS.items():
            for i, (problema, estado, equipo_i) in enumerate(casos, 1):
                clave = f'{MARCA}|{codigo}|{i:02d}|'
                eventos = TicketEvent.objects.filter(tipo_accion='registro', detalles__startswith=clave)
                if eventos.count() > 1:
                    raise CommandError(f'Marcador demo duplicado: {clave}. No se eligió un ticket arbitrario.')
                evento = eventos.first()
                if evento:
                    self.tickets.append(evento.ticket_id)
                elif self.solo_lectura:
                    raise CommandError(f'Falta el ticket {clave}.')
                else:
                    ticket = self.crear_ticket(codigo, i, numero, problema, estado, equipo_i, clave)
                    self.tickets.append(ticket.pk)
                    self.nuevos['Ticket'] += 1
                numero += 1

    def crear_ticket(self, codigo, i, numero, problema, estado, equipo_i, clave):
        # Para demostrar revisión, primero se reporta al área equivocada y su
        # supervisor redirige al destino correcto, siguiendo el flujo vigente.
        origen = next(c for c in self.areas if c != codigo) if estado == 'revision' else codigo
        servicio_i = (numero % 8 if equipo_i is None else
                      (tuple(EQUIPOS).index(codigo) * 4 + equipo_i) % len(self.servicios))
        datos = {
            'servicio': self.servicios[servicio_i].pk, 'area_problema': self.ubicaciones[servicio_i].pk,
            'area_soporte': self.areas[origen].pk,
            'descripcion': f'DEMO - {problema}. Caso ficticio en sala de pruebas, sin pacientes ni actividad clínica real. Se solicita revisión del síntoma observado durante la simulación.',
            'acciones_previas': 'DEMO: se registró el síntoma en un entorno simulado. No se realizaron acciones sobre equipos reales.',
        }
        if equipo_i is not None:
            datos['equipo'] = self.equipos[codigo][equipo_i].pk
        foto = SimpleUploadedFile(f'demo_{codigo}_{i:02d}.png', self.imagen(clave), 'image/png')
        solicitante = self.solicitantes[numero % 10]
        try:
            if not puede_registrar_incidencia(solicitante):
                raise CommandError('El reportante demo no está autorizado para registrar.')
            form = TicketForm(datos, {'fotografia': foto}, solicitante=solicitante)
            if not form.is_valid():
                raise CommandError('La incidencia ficticia no supera las validaciones del formulario.')
            ticket = form.save(commit=False)
            ticket.solicitante = solicitante
            # Guardado privado habitual del ImageField; registrar exactamente los
            # archivos nuevos permite retirarlos si esta carga completa revierte.
            foto.seek(0)
            ticket.fotografia.save(foto.name, ContentFile(foto.read()), save=False)
            self.archivos.append((ticket.fotografia.storage, ticket.fotografia.name))
            ticket.save()  # AUD-011; misma transacción que su evento y el escenario.
            form.save_m2m()
            TicketEvent.objects.create(
                ticket=ticket, tipo_accion='registro', usuario=solicitante,
                detalles=f'{clave} Ticket registrado: {ticket.codigo_ticket} (demostración ficticia)',
            )
        finally:
            foto.close()
        supervisor = self.supervisores[origen][(i - 1) % 3]
        prioridad = ('media', 'baja', 'alta', 'critica')[numero % 4]
        if prioridad != ticket.prioridad:
            self.ejecutar(incidencias.priorizar_ticket, supervisor, {'pk': ticket.pk}, {'prioridad': prioridad})
        if estado == 'revision':
            self.ejecutar(incidencias.redirigir_ticket, supervisor, {'pk': ticket.pk}, {'area_soporte': self.areas[codigo].pk})
        elif estado != 'registrada':
            tecnico = self.tecnicos[codigo][(i - 1) % 4]
            programada = timezone.now() + (timedelta(hours=2) if estado == 'asignada' else timedelta())
            self.ejecutar(incidencias.asignar_tecnico, supervisor, {'pk': ticket.pk}, {
                'tecnico': tecnico.pk, 'scheduled_at': programada.isoformat(),
            })
            if estado != 'asignada':
                self.ejecutar(mantenimiento.iniciar_atencion, tecnico, {'ticket_pk': ticket.pk})
                self.ejecutar(mantenimiento.registrar_atencion, tecnico, {'ticket_pk': ticket.pk}, {
                    'diagnostico': f'DEMO: síntoma reproducido en prueba simulada: {problema}.',
                    'acciones_realizadas': 'DEMO: inspección y comprobación funcional simuladas; sin intervención clínica real.',
                    'observaciones': 'Datos ficticios para presentación de funcionalidades.',
                    'materiales_requeridos': 'DEMO: material de prueba, sin consumo real.',
                    'recursos_utilizados': 'DEMO: herramientas de simulación.', 'evidencias': 'Fotografía demo adjunta al ticket.',
                })
                if estado != 'en_atencion':
                    self.ejecutar(mantenimiento.finalizar_atencion, tecnico, {'ticket_pk': ticket.pk})
                if estado in ('devuelta', 'cerrada_tecnicamente'):
                    self.ejecutar(mantenimiento.revisar_atencion, supervisor, {'ticket_pk': ticket.pk}, {
                        'decision': 'devuelto' if estado == 'devuelta' else 'aprobado',
                        'justificacion': ('DEMO: completar documentación de la prueba simulada.' if estado == 'devuelta'
                                          else 'DEMO: resultados simulados revisados; cierre autorizado para la demostración.'),
                    })
        ticket.refresh_from_db()
        if ticket.estado != estado:
            raise CommandError(f'El escenario {clave} no alcanzó el estado esperado.')
        for modelo, cantidad in (
            ('TicketAssignment', ticket.asignaciones.count()), ('AtencionTecnica', ticket.atenciones.count()),
            ('RevisionSupervisor', RevisionSupervisor.objects.filter(atencion__ticket=ticket).count()),
            ('TicketEvent', ticket.eventos.count()),
        ):
            self.nuevos[modelo] += cantidad
        return ticket

    def verificar(self):
        if len({u['username'] for u in self.usuarios}) != 32 or len(set(self.tickets)) != 15:
            raise CommandError('El conjunto demo no tiene 32 cuentas y 15 tickets distintos.')
        for ticket in Ticket.objects.filter(pk__in=self.tickets):
            if ticket.solicitante.roles != 'solicitante' or not ticket.fotografia:
                raise CommandError('Ticket demo sin solicitante válido o fotografía.')
            activas = list(ticket.asignaciones.filter(activo=True))
            if len(activas) > 1 or ticket.atenciones.count() > 1:
                raise CommandError('Asignación o intervención demo ambigua.')
            if activas:
                asignacion = activas[0]
                tecnico = asignacion.tecnico
                if (not tecnico.is_active or tecnico.roles != 'tecnico'
                        or not tecnico.areas.filter(pk=ticket.area_soporte_id).exists()
                        or asignacion.scheduled_at != ticket.scheduled_at):
                    raise CommandError('Asignación demo incoherente.')
            if ticket.codigo_ticket not in ticket.eventos.get(tipo_accion='registro').detalles:
                raise CommandError('El historial demo no conserva su código de registro.')
            if not ticket.fotografia.storage.exists(ticket.fotografia.name):
                raise CommandError('Falta una fotografía demo privada.')
            atencion = ticket.atenciones.first()
            if ticket.estado in ('registrada', 'revision'):
                if activas or atencion:
                    raise CommandError('Un escenario demo pendiente tiene trabajo iniciado.')
            else:
                if len(activas) != 1 or ticket.scheduled_at is None:
                    raise CommandError('Falta la asignación programada del escenario demo.')
                if ticket.created_at > activas[0].fecha_asignacion:
                    raise CommandError('Cronología demo inválida.')
            if ticket.estado in ('en_atencion', 'pendiente_validacion', 'devuelta', 'cerrada_tecnicamente'):
                if (atencion is None or atencion.tecnico_id != activas[0].tecnico_id
                        or atencion.work_started_at is None
                        or atencion.work_started_at < activas[0].fecha_asignacion
                        or not atencion.diagnostico or not atencion.acciones_realizadas):
                    raise CommandError('Intervención demo incompleta o incoherente.')
                finalizada = ticket.estado != 'en_atencion'
                if (atencion.finalizado_por_tecnico != finalizada
                        or atencion.enviado_a_revision != finalizada
                        or (atencion.work_finished_at is not None) != finalizada):
                    raise CommandError('Indicadores de finalización demo incoherentes.')
                if finalizada and atencion.work_finished_at < atencion.work_started_at:
                    raise CommandError('La finalización demo precede al inicio.')
                if ticket.estado in ('devuelta', 'cerrada_tecnicamente'):
                    revision = atencion.revisiones.order_by('-fecha_decision', '-pk').first()
                    esperada = 'devuelto' if ticket.estado == 'devuelta' else 'aprobado'
                    if revision is None or revision.decision != esperada or revision.fecha_decision < atencion.work_finished_at:
                        raise CommandError('Falta revisión coherente del escenario demo.')
            if ticket.estado == 'cerrada_tecnicamente':
                if ticket.closed_at is None or ticket.closed_at < atencion.work_finished_at:
                    raise CommandError('Fecha de cierre demo incoherente.')
            elif ticket.closed_at is not None:
                raise CommandError('Un ticket demo abierto tiene fecha de cierre.')

    def resumen(self):
        tickets = Ticket.objects.filter(pk__in=self.tickets)
        totales = {
            'Area': len(self.areas), 'Servicio': len(self.servicios), 'AreaProblema': len(self.ubicaciones),
            'Equipment': sum(len(e) for e in self.equipos.values()), 'User': len(self.usuarios), 'Ticket': tickets.count(),
            'TicketAssignment': TicketAssignment.objects.filter(ticket__in=tickets).count(),
            'AtencionTecnica': AtencionTecnica.objects.filter(ticket__in=tickets).count(),
            'RevisionSupervisor': RevisionSupervisor.objects.filter(atencion__ticket__in=tickets).count(),
            'TicketEvent': TicketEvent.objects.filter(ticket__in=tickets).count(),
        }
        return {
            'conjunto': MARCA, 'base_local': connection.settings_dict['NAME'],
            'modo': 'verificación sin escrituras' if self.solo_lectura else 'carga idempotente',
            'creados': dict(self.nuevos),
            'reutilizados': {nombre: total - self.nuevos[nombre] for nombre, total in totales.items()},
            'totales_demo': {'areas': len(self.areas), 'servicios': len(self.servicios), 'ubicaciones': len(self.ubicaciones),
                             'equipos': sum(len(e) for e in self.equipos.values()), 'usuarios': len(self.usuarios), 'tickets': tickets.count(),
                             'asignaciones': TicketAssignment.objects.filter(ticket__in=tickets).count(),
                             'intervenciones': AtencionTecnica.objects.filter(ticket__in=tickets).count(),
                             'revisiones': RevisionSupervisor.objects.filter(atencion__ticket__in=tickets).count(),
                             'eventos': TicketEvent.objects.filter(ticket__in=tickets).count()},
            'por_rol': dict(Counter(u['rol'] for u in self.usuarios)),
            'tickets_por_estado': dict(Counter(tickets.values_list('estado', flat=True))),
            'tickets_por_area': dict(Counter(tickets.values_list('area_soporte__codigo', flat=True))),
            'credenciales': 'Solo las cuentas nuevas usan SGIM_DEMO_PASSWORD. Las existentes conservan sus claves.',
        }
