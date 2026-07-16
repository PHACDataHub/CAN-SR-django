# syntax=docker/dockerfile:1.7

FROM python:3.13.5-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY requirements.txt ./
RUN python -m pip wheel --wheel-dir /wheels -r requirements.txt


FROM python:3.13.5-slim-bookworm AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/home/app/.local/bin:${PATH}"

WORKDIR /app/src

RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home app

COPY requirements.txt /app/requirements.txt
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels \
        -r /app/requirements.txt \
    && rm -rf /wheels

COPY --chown=app:app src /app/src
COPY docker/entrypoint.sh /usr/local/bin/can-sr-entrypoint

RUN chmod 0755 /usr/local/bin/can-sr-entrypoint \
    && rm -rf /app/src/tests \
    && mkdir -p /app/src/media /app/src/staticfiles \
    && chown -R app:app /app/src/media /app/src/staticfiles \
    && SECRET_KEY=build-only-secret \
       ALLOWED_HOSTS=localhost \
       USE_SQLITE=1 \
       GROBID_URL=dev \
       python manage.py collectstatic --noinput

USER app

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/can-sr-entrypoint"]
CMD ["gunicorn", "proj.wsgi:application", "--bind=0.0.0.0:8000", "--access-logfile=-", "--error-logfile=-", "--capture-output", "--timeout=120", "--graceful-timeout=30"]


FROM runtime AS test

USER root

ENV SECRET_KEY=test-only-secret \
    ALLOWED_HOSTS=localhost,testserver \
    USE_SQLITE=1 \
    GROBID_URL=dev

COPY requirements_test.txt /app/
RUN python -m pip install --no-cache-dir \
        -r /app/requirements_test.txt

COPY --chown=app:app src/tests /app/src/tests

USER app