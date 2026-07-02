FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright na browser moja tu
RUN pip install playwright==1.61.0
RUN playwright install chromium --with-deps

COPY . .

CMD ["python", "tg_bot/main.py"]
