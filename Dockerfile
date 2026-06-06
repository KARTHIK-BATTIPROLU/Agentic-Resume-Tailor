# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# --- System deps: tectonic runtime libraries + curl for the installer ---------
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
        fontconfig libfontconfig1 libfreetype6 libgraphite2-3 libharfbuzz0b \
        libicu72 libssl3 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# --- Install tectonic (LaTeX engine) and verify it -----------------------------
RUN curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh \
    && mv tectonic /usr/local/bin/tectonic \
    && chmod +x /usr/local/bin/tectonic \
    && tectonic --version

WORKDIR /app

# --- Python deps (CPU-only torch to keep the image lean) -----------------------
COPY requirements.txt .
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

# --- Pre-download the embedding model so requests are fast & offline-capable ---
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# --- Warm the tectonic package cache so the first render needs no network ------
RUN printf '%s\n' \
        '\documentclass[11pt]{article}' \
        '\usepackage[T1]{fontenc}' \
        '\usepackage[utf8]{inputenc}' \
        '\usepackage[margin=0.6in]{geometry}' \
        '\usepackage{enumitem}' \
        '\usepackage{titlesec}' \
        '\usepackage{hyperref}' \
        '\usepackage{xcolor}' \
        '\begin{document}cache warm\end{document}' > /tmp/warm.tex \
    && tectonic /tmp/warm.tex \
    && rm -f /tmp/warm.tex /tmp/warm.pdf

# --- App code ------------------------------------------------------------------
COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
