FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 DATA_DIR=/data IMPORT_DIR=/import TZ=Europe/Copenhagen
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

VOLUME ["/data", "/import"]
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
