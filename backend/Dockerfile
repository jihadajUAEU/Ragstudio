FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ffmpeg \
        git \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libjpeg62-turbo \
        libpng16-16 \
        libsm6 \
        libxext6 \
        libxrender1 \
        wget \
    && rm -rf /var/lib/apt/lists/*

COPY constraints/runtime-latest.txt /app/constraints/runtime-latest.txt
COPY scripts/patch_paddlex_wheel.py /tmp/patch_paddlex_wheel.py
COPY scripts/runtime_import_smoke.py /tmp/runtime_import_smoke.py

RUN python -m pip install --upgrade pip setuptools wheel \
    && mkdir -p /tmp/paddlex-wheel /tmp/patched-wheels \
    && python -m pip download --no-deps --dest /tmp/paddlex-wheel paddlex==3.5.1 \
    && python /tmp/patch_paddlex_wheel.py /tmp/paddlex-wheel /tmp/patched-wheels \
    && python -m pip install --no-deps --no-index --find-links=/tmp/patched-wheels paddlex==3.5.1

COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY pyproject.toml /app/pyproject.toml
COPY backend/src /app/backend/src
COPY backend/tests /app/backend/tests

RUN python -m pip install \
        --find-links=/tmp/patched-wheels \
        -c /app/constraints/runtime-latest.txt \
        -e "backend[dev]" \
    && python -m pip check \
    && python /tmp/runtime_import_smoke.py

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "ragstudio.app:create_app", "--factory", "--reload", "--app-dir", "backend/src", "--host", "0.0.0.0", "--port", "8000"]
