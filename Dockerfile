FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN groupadd -r transcriber && useradd -r -g transcriber transcriber
RUN mkdir -p /models && chown transcriber:transcriber /models
USER transcriber
CMD ["python", "-m", "signal_transcriber"]
