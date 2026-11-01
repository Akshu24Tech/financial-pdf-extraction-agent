# FinAgent web demo as a container image.
#
#   docker build -t finagent .
#   docker run -p 8501:8501 finagent        -> http://localhost:8501
#
# Why a container (interview answer): it packages Python, the exact
# dependencies, and the app into one image that runs the same on my laptop,
# in CI, and on any cloud host. "Works on my machine" stops being a thing.

# --- Base image ---------------------------------------------------------------
# "slim" = Debian with only the essentials (~50 MB vs ~400 MB for the full image).
# Pinned to 3.12 because CI already tests 3.12, so the image runs a tested version.
FROM python:3.12-slim

# Don't write .pyc files; flush logs immediately so `docker logs` shows them live.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8501

WORKDIR /app

# --- Dependencies FIRST (layer caching) --------------------------------------
# Docker caches each step. Copying only requirements.txt before the code means
# the slow `pip install` layer is reused on every rebuild unless the
# dependencies themselves change. Edit app.py -> rebuild takes seconds, not minutes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# --- Application code ----------------------------------------------------------
# .dockerignore keeps .venv, test_pdfs, output, .git etc. out of the image.
COPY finagent/ finagent/
COPY samples/ samples/
COPY app.py .

# --- Security: don't run as root ---------------------------------------------
# If the app were ever exploited, the attacker gets an unprivileged user,
# not root inside the container.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8501

# --- Health check ---------------------------------------------------------------
# Streamlit serves /_stcore/health. Docker (and hosts) mark the container
# unhealthy if it stops answering, e.g. after the OOM kill we saw on
# Streamlit Cloud. Uses Python because the slim image has no curl.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/_stcore/health', timeout=4)"

# --- Start ---------------------------------------------------------------------
# 0.0.0.0 = listen on all interfaces; the default (localhost) would be
# unreachable from outside the container. Shell form so $PORT expands:
# hosts like Render / Cloud Run / HF Spaces tell the app which port to use.
CMD streamlit run app.py \
    --server.address=0.0.0.0 \
    --server.port=${PORT} \
    --server.headless=true \
    --browser.gatherUsageStats=false
