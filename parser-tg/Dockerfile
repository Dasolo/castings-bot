FROM python:3.12-slim

WORKDIR /app

COPY parser-tg/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY parser-tg/src/ ./src/

CMD ["python", "-m", "src.main"]
