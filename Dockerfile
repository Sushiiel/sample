FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates wget libssl-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY app.py /app/app.py

RUN python -m pip install --upgrade pip setuptools wheel
RUN pip install -r /app/requirements.txt

EXPOSE 8080
CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4"]
