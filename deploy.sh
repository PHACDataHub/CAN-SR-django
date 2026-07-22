#!/usr/bin/env bash

# Deploy the CAN-SR Django application as a local Docker Compose demo.
# GROBID is enabled by default so PDF parsing uses the real service.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BUILD=false
DEMO=false
RESET_DB=false
USE_GROBID=true
WAIT_TIMEOUT=${DEPLOY_WAIT_TIMEOUT:-180}

usage() {
    cat <<'USAGE'
CAN-SR Django - local Docker deployment

Usage: ./deploy.sh [OPTIONS]

Options:
  --build       Build the Django image before starting services
  --demo        Create local demo data and the admin/admin demo account
  --reset-db    Delete local PostgreSQL and media volumes before deployment
  --no-grobid   Use canned GROBID responses instead of the real service
  -h, --help    Show this help message

Examples:
  ./deploy.sh --build --demo   Build and launch a populated localhost demo
  ./deploy.sh                  Start/update the normal stack with real GROBID
  ./deploy.sh --no-grobid      Lightweight UI/testing mode (simulated parsing)

This script is intended for local development and demonstrations, not a
production deployment. The --demo credentials are intentionally insecure.
USAGE
}

while (($#)); do
    case "$1" in
        --build)
            BUILD=true
            ;;
        --demo)
            DEMO=true
            ;;
        --reset-db)
            RESET_DB=true
            ;;
        --no-grobid)
            USE_GROBID=false
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

info() {
    printf '\033[0;34m==>\033[0m %s\n' "$*"
}

success() {
    printf '\033[0;32mOK:\033[0m %s\n' "$*"
}

warn() {
    printf '\033[1;33mWARNING:\033[0m %s\n' "$*" >&2
}

fail() {
    printf '\033[0;31mERROR:\033[0m %s\n' "$*" >&2
    exit 1
}

compose() {
    if [[ "$USE_GROBID" == true ]]; then
        GROBID_URL=http://grobid:8070/ docker compose --profile grobid "$@"
    else
        GROBID_URL=dev docker compose "$@"
    fi
}

service_container_id() {
    compose ps --quiet "$1"
}

service_status() {
    local container_id
    container_id=$(service_container_id "$1")
    if [[ -z "$container_id" ]]; then
        printf 'missing'
        return
    fi

    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id"
}

wait_for_service() {
    local service=$1
    local deadline=$((SECONDS + WAIT_TIMEOUT))
    local status

    info "Waiting for $service to become healthy"
    while ((SECONDS < deadline)); do
        status=$(service_status "$service")
        case "$status" in
            healthy|running)
                success "$service is $status"
                return 0
                ;;
            unhealthy|exited|dead)
                compose logs --tail=100 "$service" >&2 || true
                fail "$service entered state: $status"
                ;;
        esac
        sleep 2
    done

    compose logs --tail=100 "$service" >&2 || true
    fail "Timed out after ${WAIT_TIMEOUT}s waiting for $service (last state: ${status:-unknown})"
}

command -v docker >/dev/null 2>&1 || fail 'Docker is not installed or is not on PATH.'
docker info >/dev/null 2>&1 || fail 'Docker is not running or is not accessible.'
docker compose version >/dev/null 2>&1 || fail 'Docker Compose v2 is not available.'

if [[ ! -f .env ]]; then
    cp .env.example .env
    success 'Created .env from .env.example; existing files are never overwritten.'
fi

if [[ "$RESET_DB" == true ]]; then
    warn 'Deleting the local PostgreSQL database and uploaded media volumes.'
    compose down --volumes --remove-orphans
fi

if [[ "$BUILD" == true ]]; then
    info 'Building the Django runtime image'
    compose build web worker
fi

info 'Starting PostgreSQL'
compose up -d postgres --remove-orphans
wait_for_service postgres

if [[ "$USE_GROBID" == true ]]; then
    info 'Starting GROBID (the first image pull and startup can take several minutes)'
    compose up -d grobid --remove-orphans
    wait_for_service grobid
else
    warn 'GROBID is disabled; PDF parsing will use canned responses.'
fi

info 'Applying database migrations'
compose run --rm --no-deps web python manage.py migrate --noinput

info 'Loading language-model configuration'
compose run --rm --no-deps web \
    python manage.py loaddata my_app/fixtures/language_models.yaml

if [[ "$DEMO" == true ]]; then
    info 'Creating demo data when it is not already present'
    compose run --rm --no-deps web \
        python manage.py runscript my_app.scripts.dev
fi

info 'Starting the web application and background worker'
compose up -d web worker --remove-orphans
wait_for_service web

printf '\n'
compose ps
printf '\n'
success 'CAN-SR Django is ready.'
printf 'Website:       http://localhost:%s\n' "${WEB_PORT:-8000}"
printf 'Health check:  http://localhost:%s/health/live\n' "${WEB_PORT:-8000}"
if [[ "$DEMO" == true ]]; then
    printf 'Demo login:    admin / admin\n'
fi
printf '\nLogs:          docker compose%s logs -f web worker grobid\n' "$([[ "$USE_GROBID" == true ]] && printf ' --profile grobid')"
printf 'Stop:          docker compose%s down\n' "$([[ "$USE_GROBID" == true ]] && printf ' --profile grobid')"
