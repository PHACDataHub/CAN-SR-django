#!/bin/sh
set -eu

echo "Starting SSH server..."
service ssh start

echo "Generating static files..."
gosu app567 python manage.py collectstatic --noinput

# Sidecars must set RUN_MIGRATIONS=false, Main container defaults to true.
case "$(printf '%s' "${RUN_MIGRATIONS:-true}" | tr '[:upper:]' '[:lower:]')" in
    true | 1 | yes) run_migrations=true ;;
    false | 0 | no) run_migrations=false ;;
    *)
        echo "ERROR: RUN_MIGRATIONS must be true or false, got '${RUN_MIGRATIONS}'." >&2
        exit 1
        ;;
esac

if [ -n "${DB_HOST:-}" ] && [ -n "${DB_PORT:-}" ]; then
    echo "Waiting for PostgreSQL (${DB_HOST}:${DB_PORT})..."
    until nc -z "$DB_HOST" "$DB_PORT"; do
        sleep 0.1
    done

    if [ "$run_migrations" = true ]; then
        echo "Applying database migrations..."
        gosu app567 python manage.py migrate --noinput
    else
        echo "Skipping database migrations (RUN_MIGRATIONS=${RUN_MIGRATIONS})."
    fi
fi

# Make App Service environment variables available in SSH login shells.
printenv | sed -n 's/^\([^=]\+\)=\(.*\)$/export \1="\2"/p' > /etc/profile.d/app-env.sh
chmod 0600 /etc/profile.d/app-env.sh

exec gosu app567 "$@"
