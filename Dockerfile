FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Tokyo
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py kosatsu.py extra.py ./
COPY static ./static
RUN useradd -m app && chown -R app /app
USER app
# ACCESS_TOKEN (required) and XAI_API_KEY (optional) are injected by the host at runtime; nothing is baked in.
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
