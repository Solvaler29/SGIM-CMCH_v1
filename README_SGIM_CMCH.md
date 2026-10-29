# SGIM-CMCH --- Sistema de Gestión de Incidencias y Mantenimiento

Guía para instalar, ejecutar y compartir el proyecto en un equipo de
desarrollo.

## 1. Requisitos

Instala en tu computadora:

-   Python 3.12 (o la versión compatible indicada por el equipo).
-   Docker Desktop, con Docker Compose.
-   Git, si vas a clonar o subir el proyecto a GitHub.

Comprueba las instalaciones desde PowerShell:

``` powershell
python --version
docker --version
docker compose version
git --version
```

## 2. Obtener el código

Clona el repositorio (reemplaza `USUARIO` y `REPOSITORIO` por los
valores reales):

``` powershell
git clone https://github.com/USUARIO/REPOSITORIO.git
cd REPOSITORIO
```

Si recibiste el proyecto en un archivo ZIP, descomprímelo y abre
PowerShell en la carpeta que contiene `manage.py`.

## 3. Configurar las variables de entorno

Crea tu propio archivo `.env` copiando el archivo de ejemplo:

``` powershell
Copy-Item .env.example .env
notepad .env
```

Revisa las variables de base de datos y ajústalas para que coincidan con
`docker-compose.yml` y con `sgim_cmch/settings.py`. En la configuración
de desarrollo usada originalmente por el proyecto se empleó PostgreSQL,
base de datos `sgim_cmch`, usuario `sgim_user`, host `localhost` y
puerto de la computadora `5433` (PostgreSQL escucha normalmente en el
puerto `5432` dentro del contenedor).

Ejemplo orientativo; utiliza la contraseña local que hayas configurado y
no copies contraseñas reales de otra persona:

``` env
DB_NAME=sgim_cmch
DB_USER=sgim_user
DB_PASSWORD=CAMBIA_ESTA_CLAVE
DB_HOST=localhost
DB_PORT=5433
```

**Importante:** los nombres y valores deben coincidir con los que espera
tu `docker-compose.yml`. No compartas el archivo `.env`, contraseñas,
`SECRET_KEY` ni otros secretos. Comparte solamente `.env.example` sin
secretos reales.

## 4. Iniciar PostgreSQL con Docker

Desde la carpeta del proyecto (donde está `docker-compose.yml`):

``` powershell
docker compose up -d
docker compose ps
```

Si necesitas revisar los registros del contenedor:

``` powershell
docker compose logs
```

Para detener los servicios:

``` powershell
docker compose down
```

Este comando detiene y elimina los contenedores de Compose, pero
normalmente conserva los datos guardados en un volumen nombrado. No uses
`docker compose down -v` salvo que quieras borrar el volumen y los datos
de la base de datos.

## 5. Crear el entorno de Python e instalar dependencias

Desde la carpeta donde está `manage.py`:

``` powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Si PowerShell bloquea la activación del entorno, puedes ejecutar los
comandos de instalación usando `.\.venv\Scripts\python.exe` sin activar
el entorno.

## 6. Crear las tablas de Django

Con PostgreSQL iniciado y las variables `.env` correctas:

``` powershell
python manage.py check
python manage.py migrate
```

Las migraciones incluidas en el repositorio crean las tablas de la
aplicación. No es necesario compartir la base de datos física para
empezar con una base nueva, siempre que las migraciones estén incluidas
y actualizadas.

Si modificas modelos durante el desarrollo, normalmente debes generar y
versionar sus migraciones:

``` powershell
python manage.py makemigrations
python manage.py migrate
```

## 7. Crear un usuario administrador

``` powershell
python manage.py createsuperuser
```

Sigue las indicaciones de la terminal para crear las credenciales
locales.

## 8. Ejecutar el sistema

``` powershell
python manage.py runserver
```

Abre en el navegador:

-   Aplicación: http://127.0.0.1:8000/
-   Administración de Django: http://127.0.0.1:8000/admin/

Para detener el servidor, vuelve a la terminal y presiona `Ctrl+C`.

## 9. Subir el proyecto a GitHub

### A. Crear el repositorio en GitHub

1.  Entra en https://github.com/ e inicia sesión.
2.  Pulsa **New repository**.
3.  Escribe un nombre, por ejemplo `SGIM-CMCH`.
4.  Elige **Private** si solo quieres compartirlo con tus compañeros
    invitados, o **Public** si deseas que cualquiera pueda verlo.
5.  Si el proyecto ya existe en tu computadora, crea el repositorio
    vacío: no marques la opción de añadir README, `.gitignore` o
    licencia en GitHub.
6.  Crea el repositorio y copia su URL HTTPS.

### B. Verificar archivos que no deben subirse

Antes de subir nada, revisa `.gitignore`. Debe excluir, como mínimo:

``` gitignore
.env
.venv/
__pycache__/
*.py[cod]
db.sqlite3
staticfiles/
media/
```

No ignores las migraciones de Django: las carpetas `migrations/` y sus
archivos `*.py` normalmente deben subirse al repositorio. Revisa también
que `.env.example` no contenga contraseñas reales ni claves privadas.

Si alguna vez ya agregaste `.env` al control de versiones, quitarlo del
seguimiento con `git rm --cached .env` no invalida una contraseña que ya
se publicó: cambia las credenciales expuestas y limpia el historial si
corresponde.

### C. Inicializar Git y subir el código

Abre PowerShell en la carpeta raíz del proyecto, la que contiene
`manage.py`, y ejecuta:

``` powershell
git init
git status
git add .
git status
git commit -m "Primer commit de SGIM-CMCH"
git branch -M main
git remote add origin https://github.com/USUARIO/REPOSITORIO.git
git push -u origin main
```

Reemplaza la URL de ejemplo por la URL real del repositorio que creaste.
Antes de `git commit`, revisa el segundo `git status` y confirma que
`.env`, `.venv` y otros archivos privados no estén incluidos. Si Git
dice que `origin` ya existe, no repitas `git remote add origin`; revisa
con `git remote -v`.

GitHub puede pedirte autenticarte desde el navegador o mediante el
método de autenticación que tengas configurado.

## 10. Dar acceso a tus compañeros

Si el repositorio es privado:

1.  Abre el repositorio en GitHub.
2.  Ve a **Settings** y busca la sección de acceso/colaboradores.
3.  Invita a tus compañeros por su usuario de GitHub.
4.  Cuando acepten, podrán clonar el repositorio con `git clone`.

Cada compañero tendrá su propia base de datos local. Los cambios de
código se comparten mediante Git; los datos de PostgreSQL no se
sincronizan automáticamente entre computadoras.

## 11. Problemas frecuentes

-   **No conecta a PostgreSQL:** verifica que Docker esté activo, que el
    contenedor esté en ejecución y que `DB_NAME`, `DB_USER`,
    `DB_PASSWORD`, `DB_HOST` y `DB_PORT` coincidan en `.env`,
    `docker-compose.yml` y la configuración de Django.
-   **El puerto 5433 ya está ocupado:** detén el servicio que lo utiliza
    o acuerda con el equipo otro puerto y actualiza la configuración de
    manera coherente.
-   **Faltan tablas:** ejecuta `python manage.py migrate` y comprueba
    que las migraciones de las aplicaciones estén versionadas.
-   **No se reconoce un comando de Docker:** abre Docker Desktop y
    espera a que termine de iniciar.
-   **No se debe subir `.env`:** verifica `.gitignore` y `git status`
    antes de cada commit.

## 12. ¿Código o copia de la base de datos?

Para que tus compañeros ejecuten el proyecto, normalmente basta con
compartir el código, las migraciones y la configuración de ejemplo. Cada
uno crea sus propias tablas al ejecutar `python manage.py migrate`.

Si necesitan datos de demostración, es preferible crear datos ficticios
de prueba o preparar un respaldo revisado que no incluya contraseñas,
datos personales ni información confidencial. No publiques una copia de
producción en GitHub.

------------------------------------------------------------------------

**Nota para el equipo:** antes de distribuir esta guía, comprueba que
`docker-compose.yml`, `.env.example`, `requirements.txt` y `.gitignore`
estén actualizados y sean coherentes entre sí.
