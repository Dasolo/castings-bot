FROM python:3.12-slim

WORKDIR /app

COPY sender/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY sender/src/ ./src/

CMD ["python", "-m", "src.main"]
