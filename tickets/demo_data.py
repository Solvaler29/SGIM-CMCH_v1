"""Escenarios ficticios de la demostración Walter v1; no son catálogo institucional."""
SERVICIOS = (
    'Emergencia', 'Hospitalización', 'Consultorios Externos', 'Centro Quirúrgico',
    'Unidad de Cuidados Intensivos', 'Laboratorio Clínico', 'Diagnóstico por Imágenes', 'Farmacia',
)
AREAS = {
    'TI': ('Tecnologías de la Información', ('tecnologiadelainformacion', 'tecnologiasdelainformacion', 'ti')),
    'IC': ('Ingeniería Clínica', ('ingenieriaclinica', 'ic')),
    'MAN': ('Mantenimiento', ('mantenimiento', 'man', 'mant')),
}
EQUIPOS = {
    'TI': ('Computadora de admisión', 'Impresora de etiquetas', 'Impresora de red', 'Estación de trabajo'),
    'IC': ('Monitor multiparámetro', 'Bomba de infusión', 'Electrocardiógrafo', 'Desfibrilador'),
    'MAN': ('Aire acondicionado', 'Camilla hidráulica', 'UPS eléctrica', 'Equipo de iluminación'),
}
# (problema, estado alcanzado por las operaciones existentes, índice de equipo o None)
CASOS = {
    'TI': (
        ('Computadora de admisión no enciende al pulsar el botón de inicio', 'registrada', 0),
        ('Impresora de etiquetas sin conexión con la estación de admisión', 'revision', 1),
        ('No se puede acceder a la aplicación de consulta desde la estación', 'asignada', 3),
        ('Estación de trabajo presenta lentitud al abrir aplicaciones', 'en_atencion', 3),
        ('Interrupción de red al enviar documentos a la impresora', 'pendiente_validacion', 2),
    ),
    'IC': (
        ('Monitor multiparámetro presenta una alarma durante la prueba simulada', 'registrada', 0),
        ('Bomba de infusión interrumpe la prueba de funcionamiento', 'asignada', 1),
        ('Electrocardiógrafo muestra un error de lectura en la prueba', 'en_atencion', 2),
        ('Desfibrilador requiere revisión después de su autocomprobación', 'pendiente_validacion', 3),
        ('Pantalla del monitor no muestra correctamente los parámetros simulados', 'cerrada_tecnicamente', 0),
    ),
    'MAN': (
        ('Aire acondicionado no enfría la sala de demostración', 'registrada', 0),
        ('Luminaria presenta encendido intermitente', 'revision', 3),
        ('Fuga de agua visible bajo el lavamanos de la sala ficticia', 'asignada', None),
        ('Puerta de la sala ficticia no cierra correctamente', 'devuelta', None),
        ('UPS eléctrica presenta una alarma al realizar una prueba sin carga clínica', 'cerrada_tecnicamente', 2),
    ),
}
