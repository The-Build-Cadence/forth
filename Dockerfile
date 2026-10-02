# syntax=docker/dockerfile:1.7

FROM node:24.15.0 AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* frontend/angular.json frontend/tsconfig.json frontend/tsconfig.app.json ./
COPY frontend/src ./src
RUN --mount=type=cache,target=/root/.npm npm install --no-audit --no-fund
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        antiword \
        libpq5 \
        poppler-utils \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY Pipfile Pipfile.lock ./
RUN pip install --no-cache-dir pipenv \
    && pipenv sync --system

COPY backend ./backend
COPY --from=frontend-build /app/frontend/dist/forth-web/browser /app/backend/staticfiles
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && cd /app/backend \
    && python manage.py collectstatic --noinput

ENV PYTHONUNBUFFERED=1
WORKDIR /app/backend
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
