#!/bin/sh
set -eu

echo "Starting SSH server..."
service ssh start

echo "Generating static files..."
gosu app567 python manage.py collectstatic --noinput

if [ -n "${DB_HOST:-}" ] && [ -n "${DB_PORT:-}" ]; then
    echo "Waiting for PostgreSQL (${DB_HOST}:${DB_PORT})..."
    until nc -z "$DB_HOST" "$DB_PORT"; do
        sleep 0.1
    done

    echo "Applying database migrations..."
    gosu app567 python manage.py migrate --noinput
fi

# Make App Service environment variables available in SSH login shells.
printenv | sed -n 's/^\([^=]\+\)=\(.*\)$/export \1="\2"/p' > /etc/profile.d/app-env.sh
chmod 0600 /etc/profile.d/app-env.sh

exec gosu app567 "$@"
