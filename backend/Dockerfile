FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

ARG WHISPER_CPP_REF=v1.7.6
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates curl \
    tesseract-ocr tesseract-ocr-ara tesseract-ocr-deu tesseract-ocr-fra \
    tesseract-ocr-spa tesseract-ocr-chi-sim tesseract-ocr-chi-tra \
    tesseract-ocr-jpn tesseract-ocr-kor tesseract-ocr-rus tesseract-ocr-tur \
    git cmake build-essential \
    && git clone --depth 1 --branch "${WHISPER_CPP_REF}" https://github.com/ggerganov/whisper.cpp.git /opt/whisper.cpp \
    && cmake -S /opt/whisper.cpp -B /opt/whisper.cpp/build \
       -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=ON \
    && cmake --build /opt/whisper.cpp/build --config Release -j2 \
    && /opt/whisper.cpp/models/download-ggml-model.sh tiny \
    && ln -s /opt/whisper.cpp/build/bin/whisper-cli /usr/local/bin/whisper-cli \
    && apt-get purge -y git cmake build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /opt/whisper.cpp/.git

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
