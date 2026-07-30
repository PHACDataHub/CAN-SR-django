# Docker environments

## Local development environment

Docker Compose provides the recommended PostgreSQL-backed development stack.
It builds one Django image for both the Gunicorn web process and the database
task worker. PostgreSQL data and uploaded media are stored in named volumes.
The deployment helper starts GROBID by default because real PDF processing
depends on it; canned responses remain available only as an explicit opt-out.

### Launch the localhost demo

The deployment helper starts PostgreSQL, the real GROBID PDF parser, the
Django website, and the background worker. From the repository root, run:

```bash
./deploy.sh --build --demo
```

The first run can take several minutes while Docker downloads and starts the
GROBID image. When the script reports that CAN-SR is ready, open
<http://localhost:8000> and sign in with:

- **Username:** `admin`
- **Password:** `admin`

These intentionally insecure credentials are for a local demo only. The
liveness endpoint is <http://localhost:8000/health/live>. To follow logs or
stop the demo:

```bash
docker compose --profile grobid logs -f web worker grobid
docker compose --profile grobid down
```

Subsequent starts can use `./deploy.sh`; `--demo` safely skips reviews when
demo records already exist. Use `./deploy.sh --reset-db --demo` for a
destructive fresh demo. For lightweight UI testing only, `--no-grobid`
explicitly switches PDF parsing to canned responses. Run `./deploy.sh --help`
for all options.

Port 8000 is the default. If another application already uses it, select a
different localhost port for that invocation, for example:

```bash
WEB_PORT=8001 ./deploy.sh --demo
```

### Manual first-time setup

From the repository root:

```bash
cp .env.example .env
docker compose build
docker compose up -d postgres
docker compose run --rm web python manage.py migrate --noinput
docker compose run --rm web \
  python manage.py loaddata my_app/fixtures/language_models.yaml
docker compose up -d web worker
```

Open <http://localhost:8000>. The liveness endpoint is available at
<http://localhost:8000/health/live>.

Create development records explicitly when wanted:

```bash
docker compose run --rm web python manage.py runscript my_app.scripts.dev
```

### Common commands

```bash
# Follow application logs
docker compose logs -f web worker

# Run Django checks or management commands
docker compose run --rm web python manage.py check
docker compose run --rm web python manage.py createsuperuser

# Build and run tests using the dedicated test image target
docker build --target test --tag can-sr-django:test .
docker run --rm can-sr-django:test pytest

# Stop containers while retaining database and media volumes
docker compose down

# Destructively remove local database and media volumes
docker compose down --volumes
```

Migrations and fixture loading are intentionally not performed by the image
entrypoint. Run them explicitly so web and worker startup cannot race schema
changes.

### Optional GROBID service

Set this value in `.env`:

```env
GROBID_URL=http://grobid:8070/
```

Then start the profile and application services:

```bash
docker compose --profile grobid up -d grobid web worker
```

GROBID is internal to the Compose network and is not published to the host.
To return to canned responses, set `GROBID_URL=dev` and recreate web/worker.

## Production container boilerplate

The production layout follows the shared PHAC Django pattern used by the
Prions project:

- `src/Dockerfile.prod` builds the Azure App Service image.
- `src/Dockerfile.prod.tshoot` adds PostgreSQL client tools and AzCopy for
  operational troubleshooting.
- `src/entrypoint.prod.sh` starts SSH, collects static files, waits for the
  configured database, and applies migrations.
- `docker-compose.az.yml` is the Azure/CI Compose override for a prebuilt
  `${REPOSITORY}` image.

Project-specific deployment pipelines are intentionally not included. They
must supply the Azure service connection, registry/repository, and App Service
names.

### Host-based development

The existing virtual-environment workflow below remains supported. To use the
Compose PostgreSQL service from a host Python process, create a local-only
`compose.override.yaml` that binds PostgreSQL to `127.0.0.1`; production-style
definitions intentionally do not publish port 5432.
