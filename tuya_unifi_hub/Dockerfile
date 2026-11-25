ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.11-alpine3.19
FROM ${BUILD_FROM}

ENV LANG C.UTF-8

# Zainstaluj zależności systemowe
RUN apk add --no-cache \
    gcc \
    musl-dev \
    libffi-dev \
    openssl-dev \
    cargo \
    curl

WORKDIR /app

# Kopiuj pliki zależności
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Kopiuj kod aplikacji
COPY app /app/
COPY run.sh /
RUN chmod a+x /run.sh

# Pobierz Bootstrap i Bootstrap Icons lokalnie (niezależność od CDN)
RUN mkdir -p /app/static && \
    curl -fsSL "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" -o /app/static/bootstrap.min.css && \
    curl -fsSL "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js" -o /app/static/bootstrap.bundle.min.js && \
    curl -fsSL "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css" -o /app/static/bootstrap-icons.css && \
    curl -fsSL "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/fonts/bootstrap-icons.woff2" -o /app/static/fonts/bootstrap-icons.woff2 || true && \
    mkdir -p /app/static/fonts && \
    curl -fsSL "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/fonts/bootstrap-icons.woff2" -o /app/static/fonts/bootstrap-icons.woff2 || true

CMD [ "/run.sh" ]
