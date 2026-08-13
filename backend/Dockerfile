# MemOS backend — REST API + MCP server
#
# Build: docker build -f backend/Dockerfile -t memos-backend .
# Run:   docker run --rm -p 8000:8000 -v memos-data:/data memos-backend

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/memos

COPY backend/pyproject.toml ./
COPY backend/src ./src

RUN pip install --no-cache-dir ".[api,mcp]"

ENV MEMOS_STORAGE_BACKEND=sqlite \
    MEMOS_VECTOR_STORE_BACKEND=sqlite \
    MEMOS_GRAPH_STORE_BACKEND=sqlite \
    MEMOS_DATABASE_PATH=/data/memos_metadata.db \
    MEMOS_VECTOR_DB_PATH=/data/memos_vectors.db \
    MEMOS_GRAPH_DB_PATH=/data/memos_graph.db

RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "memos.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
