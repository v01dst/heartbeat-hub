FROM python:3.14-slim
WORKDIR /app
COPY app ./app
ENV PYTHONUNBUFFERED=1 PORT=3000 DB_PATH=/app/data/heartbeats.db
RUN mkdir -p /app/data
VOLUME /app/data
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request;urllib.request.urlopen('http://localhost:3000/health',timeout=3)"
CMD ["python3", "-m", "app.main"]
