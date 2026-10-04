FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
# ffmpeg: conversão das gravações do roteiro e do TTS para OGG/Opus (nota de voz do WhatsApp).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN useradd --create-home --uid 10001 crm
COPY --chown=crm:crm . .
RUN mkdir -p /app/staticfiles /app/media && chown crm:crm /app/staticfiles /app/media
USER crm
EXPOSE 8000
# Em produção, sobrescreva FORWARDED_ALLOW_IPS com o nome/IP do serviço "proxy" do
# Docker Compose (ex.: o nome do serviço Caddy na rede interna), nunca com "*" —
# confiar em X-Forwarded-* de qualquer origem permite spoofing de IP/proto do cliente.
ENV FORWARDED_ALLOW_IPS=127.0.0.1
CMD ["sh", "-c", "uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\""]
