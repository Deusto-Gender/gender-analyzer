FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN sed -i 's/\r//g' requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
# Download spaCy Spanish model: lg -> md -> sm fallback
RUN python -m spacy download es_core_news_lg || python -m spacy download es_core_news_md || python -m spacy download es_core_news_sm
# Download WordNet data for optional Spanish expansion
RUN python -c "import nltk; nltk.download('omw-1.4', quiet=True); nltk.download('wordnet', quiet=True)" || true
# Smoke-test: single-line assert
RUN python -c "import spacy, importlib.util; found=[m for m in ['es_core_news_lg','es_core_news_md','es_core_news_sm'] if importlib.util.find_spec(m.replace('-','_'))]; assert found, 'No spaCy model found'; nlp=spacy.load(found[0]); print('spaCy OK:', found[0], nlp.meta['version'])"
COPY main.py .
EXPOSE 8002
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
