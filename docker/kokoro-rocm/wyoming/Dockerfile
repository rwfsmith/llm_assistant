FROM python:3.12-slim

# Install Wyoming library and async HTTP client
RUN pip install --no-cache-dir "wyoming>=1.8.0" "aiohttp>=3.9"

WORKDIR /app
COPY server.py .

EXPOSE 10200

ENTRYPOINT ["python", "-u", "server.py"]
