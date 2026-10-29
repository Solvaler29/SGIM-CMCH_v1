# SGIM-CMCH - Sistema de Gestión de Incidencias y Mantenimiento del CMCH

Sistema web para gestión de incidencias y mantenimiento en una clínica, desarrollado con Django, PostgreSQL, HTML, CSS, JavaScript y Bootstrap.

## Arquitectura

- **Backend:** Python + Django (monolito modular)
- **Base de datos:** PostgreSQL (configurada por variables de entorno)
- **Frontend:** HTML5, CSS3, JavaScript, Bootstrap 5
- **Plantillas:** Django Templates
- **Escaneo QR:** html5-qrcode (vía CDN) o entrada manual de identificador QR
- **Autenticación:** Django Auth con modelo de usuario personalizado
- **Archivos subidos:** Almacenamiento privado en `media/`

## Estructura de Carpetas

```
proy/
├── manage.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── sgim_cmch/           # Configuración del proyecto Django
│   ├── __init__.py
│   ├── settings.py      # Conexión PostgreSQL y variables de entorno
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── accounts/            # Usuarios, roles y áreas
├── core/                # Áreas y servicios
├── equipment/           # Catálogo de equipos simulados y consulta QR
├── tickets/             # Tickets, incidencias, historial y asignaciones
├── maintenance/         # Atenciones técnicas y revisión de supervisor
├── reports/             # Paneles e informes
├── templatetags/        # Filtros personalizados de plantilla
├── templates/           # Plantillas HTML
├── static/              # CSS y JS
├── media/               # Evidencias subidas (privado en producción)
└── db.sqlite3           # Solo si se usa SQLite (no recomendado para producción)
```

## Requisitos

- Python 3.10+
- PostgreSQL 14+
- pip (gestor de paquetes de Python)

## Instalación y Ejecución

### 1. Crear y activar entorno virtual
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
```

### 2. Instalar dependencias

## Flujo de una Incidencia

1. **Solicitante** se registra e inicia sesión.
2. **Solicitante** registra una incidencia (opcional: escanea QR para identificar equipo, adjunta fotografía obligatoria).
3. **Supervisor/Planificador** revisa, clasifica, establece prioridad, programa fecha estimada y asigna técnico.
4. **Técnico** inicia la atención, registra diagnóstico, acciones y recursos, y finaliza la intervención.
5. **Supervisor** revisa y aprueba el cierre técnico o devuelve para correcciones.
6. **Solicitante** consulta estado e historial, y responde encuesta de satisfacción.
7. Si es necesario, el ticket puede reabrirse conservando la información previa.

## Seguridad

- Autenticación individual con contraseñas gestionadas por Django.
- Permisos verificados en el backend (no solo ocultando botones).
- Protección CSRF activada.
- Validación de extensión, tipo y tamaño de archivos subidos.
- Fotografías almacenadas de forma privada (no accesibles mediante enlaces públicos).
- Variables de entorno para secretos (no en el código fuente).
- `DEBUG=False` y cookies seguras en producción.
- Restricciones por área y asignación en consultas y vistas.

## Despliegue en Producción

1. Configura `DEBUG=False` en `.env`.
2. Configura `ALLOWED_HOSTS` con el dominio del servidor.
3. Usa HTTPS (certificado SSL/TLS).
4. Configura `SECURE_SSL_REDIRECT=True`, `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`.
5. Sirve archivos estáticos con un servidor web (Nginx/Apache).
6. Configura copias de seguridad regulares de PostgreSQL.
7. Restringe el acceso a PostgreSQL desde redes autorizadas.

## Copias de Seguridad y Restauración

```bash
# Respaldo
pg_dump -U sgim_user -d sgim_cmch > respaldo.sql

# Restauración
psql -U sgim_user -d sgim_cmch < respaldo.sql
```

## Notas

- Los datos de equipos y tickets son ficticios. No se almacenan datos clínicos reales.
- El QR solo identifica un equipo y recupera sus datos básicos simulados.
- Para probar el escáner QR en celular se requiere cámara y contexto seguro (HTTPS en producción).
- Si no hay cámara disponible, se puede probar con la entrada manual de identificador QR o la lista de equipos simulados.
```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno
```bash
cp .env.example .env
```

Edita `.env` con tus credenciales de PostgreSQL:
```
SECRET_KEY=tu-clave-secreta-aqui
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
DB_NAME=sgim_cmch
DB_USER=sgim_user
DB_PASSWORD=tu-contraseña-segura
DB_HOST=localhost
DB_PORT=5432
TIME_ZONE=America/Bogota
```

> **Importante:** El archivo `.env` no se sube al repositorio (está en `.gitignore`).

### 4. Crear base de datos y usuario en PostgreSQL
```sql
CREATE DATABASE sgim_cmch;
CREATE USER sgim_user WITH PASSWORD 'tu-contraseña-segura';
GRANT ALL PRIVILEGES ON DATABASE sgim_cmch TO sgim_user;
```

### 5. Ejecutar migraciones
```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Cargar equipos ficticios
```bash
python manage.py seed_equipment
```

### 7. Crear superusuario
```bash
python manage.py createsuperuser
```

### 8. Iniciar el servidor de desarrollo
```bash
python manage.py runserver
```

Accede a `http://127.0.0.1:8000/` e inicia sesión con el superusuario creado.

## Pruebas

Ejecuta las pruebas automatizadas de Django:
```bash
python manage.py test
```