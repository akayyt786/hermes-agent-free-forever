FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    && curl -sL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and dependencies
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 8000

CMD ["python", "-m", "app.main"]
