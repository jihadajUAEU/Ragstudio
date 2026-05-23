FROM jbarlow83/ocrmypdf:latest

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr-ara \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
