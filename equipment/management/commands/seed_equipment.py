"""
Comando de gestión para cargar equipos ficticios en la tabla Equipment.

Uso:
    python manage.py seed_equipment

El comando es idempotente: no crea duplicados si se ejecuta varias veces.
"""
from django.core.management.base import BaseCommand
from equipment.models import Equipment


class Command(BaseCommand):
    help = 'Carga equipos ficticios para pruebas del módulo QR'

    def handle(self, *args, **options):
        equipos_ficticios = [
            {
                'nombre': 'Monitor de Signos Vitales',
                'codigo_equipo': 'EQ-MON-001',
                'qr_identifier': 'QR-DEMO-MON-001',
                'marca': 'SimuMed',
                'modelo': 'VS-5000',
                'numero_serie': 'SN-DEMO-001',
                'ubicacion': 'Urgencias - Box 1',
                'estado_referencia': 'Operativo',
            },
            {
                'nombre': 'Bomba de Infusión',
                'codigo_equipo': 'EQ-INF-002',
                'qr_identifier': 'QR-DEMO-INF-002',
                'marca': 'MediPump',
                'modelo': 'IP-200',
                'numero_serie': 'SN-DEMO-002',
                'ubicacion': 'Hospitalización - Sala 3',
                'estado_referencia': 'Operativo',
            },
            {
                'nombre': 'Electrocardiógrafo',
                'codigo_equipo': 'EQ-ECG-003',
                'qr_identifier': 'QR-DEMO-ECG-003',
                'marca': 'CardioSim',
                'modelo': 'ECG-12C',
                'numero_serie': 'SN-DEMO-003',
                'ubicacion': 'Consultorio Cardiología',
                'estado_referencia': 'En reparación',
            },
            {
                'nombre': 'Camilla Eléctrica',
                'codigo_equipo': 'EQ-CAM-004',
                'qr_identifier': 'QR-DEMO-CAM-004',
                'marca': 'HospitalEquip',
                'modelo': 'CE-100',
                'numero_serie': 'SN-DEMO-004',
                'ubicacion': 'Quirófano 2',
                'estado_referencia': 'Operativo',
            },
            {
                'nombre': 'Ventilador Pulmonar',
                'codigo_equipo': 'EQ-VEN-005',
                'qr_identifier': 'QR-DEMO-VEN-005',
                'marca': 'BreathSim',
                'modelo': 'VP-300',
                'numero_serie': 'SN-DEMO-005',
                'ubicacion': 'UCI - Cama 5',
                'estado_referencia': 'Fuera de servicio',
            },
        ]

        creados = 0
        existentes = 0
        for datos in equipos_ficticios:
            obj, creado = Equipment.objects.update_or_create(
                qr_identifier=datos['qr_identifier'],
                defaults=datos,
            )
            if creado:
                creados += 1
            else:
                existentes += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Equipos procesados: {creados} nuevos, {existentes} actualizados (sin duplicados).'
            )
        )