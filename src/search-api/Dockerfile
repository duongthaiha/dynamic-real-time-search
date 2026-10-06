FROM python:3.13-slim
WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY pyproject.toml ./
COPY catalog_search ./catalog_search
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" . && useradd --create-home search
USER search
EXPOSE 8000
CMD ["uvicorn", "catalog_search.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
