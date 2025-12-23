FROM python:3.11-slim

# system deps for manylinux wheels & building python packages
#RUN apt-get update && apt-get install -y --no-install-recommends \
#    wget build-essential ca-certificates git \
#    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# upgrade pip first
RUN pip install --upgrade pip
	
# Install CPU torch (without torchvision)
#RUN pip install --index-url https://download.pytorch.org/whl/cpu \
#    torch==2.4.1+cpu --extra-index-url https://download.pytorch.org/whl/cpu

# then install python libs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy code
COPY . /app

ENV PROCESSED_DIR=/app/data/processed
ENV QDRANT_HOST=thai-qdrant
ENV QDRANT_PORT=6333
ENV QDRANT_COLLECTION=thai_laws

CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8001"]
#CMD ["python", "index_to_qdrant.py"]
