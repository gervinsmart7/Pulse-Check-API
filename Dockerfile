FROM python:3.12-slim

# System deps needed to build psycopg2 from source
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# App Platform injects $PORT; default to 8080 for local docker run
ENV PORT=8080
EXPOSE 8080

COPY entrypoint.sh .

ENTRYPOINT ["./entrypoint.sh"]
