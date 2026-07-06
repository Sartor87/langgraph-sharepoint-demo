FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY app ./app

RUN pip install --no-cache-dir ".[azure]" || pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "-m", "app.main"]
