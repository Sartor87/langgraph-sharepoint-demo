FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY app ./app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[azure]"

EXPOSE 8000

CMD ["python", "-m", "app.main"]
