FROM python:3.11-slim

# upgrade pip first
RUN pip install --upgrade pip

# install poppler-utils and tesseract + thai language pack
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils tesseract-ocr tesseract-ocr-tha libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
VOLUME ["/app/data/raw","/app/data/processed"]
CMD ["python","process_deep_doc.py"]
