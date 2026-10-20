FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY relay.py .
COPY static ./static
ENV RELAY_DB=/data/relay.sqlite3 PORT=8080
RUN mkdir -p /data && chown nobody /data
VOLUME /data
EXPOSE 8080
USER nobody
CMD ["python", "relay.py"]
