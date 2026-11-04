FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY policy.yaml ./
RUN mkdir -p /app/data && chown app /app/data
USER app
VOLUME ["/app/data"]
EXPOSE 8090
CMD ["ha-agent", "serve", "--host", "0.0.0.0", "--port", "8090"]
