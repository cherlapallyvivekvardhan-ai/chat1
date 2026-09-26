FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000

CMD ["gunicorn", "--worker-class", "gthread", "--threads", "8", "-w", "1", "app:app", "--bind", "0.0.0.0:8000"]
