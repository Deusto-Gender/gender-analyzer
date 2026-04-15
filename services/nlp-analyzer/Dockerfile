FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy Spanish model (try large, fallback to medium then small)
RUN python -m spacy download es_core_news_lg || \
    python -m spacy download es_core_news_md || \
    python -m spacy download es_core_news_sm

COPY main.py .

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1"]
