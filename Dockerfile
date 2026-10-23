# SparkAgent — local-first agent; container target for Linux hosts.
# The GPU tier (Ollama) is expected on the host network; without it the
# daemon routes everything to the remote tier.
FROM python:3.12-slim

WORKDIR /app

# tini gives us correct signal handling for the 24/7 daemon
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY kernel/ kernel/
COPY openshell/ openshell/
COPY brain/ brain/
COPY tools/ tools/
COPY interface/ interface/
COPY swarm/ swarm/
COPY security/ security/
COPY memory_search/ memory_search/
COPY ops/ ops/
COPY main.py .

# unprivileged runtime user; data/ and skills/ are volumes
RUN useradd --create-home --uid 1000 spark \
    && mkdir -p /app/data /app/skills \
    && chown -R spark:spark /app
USER spark

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

VOLUME ["/app/data", "/app/skills"]
EXPOSE 8788

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8788/api/health', timeout=8)" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "main.py"]
