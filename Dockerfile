FROM python:3.12-slim

WORKDIR /app

# Install system dependencies needed for cloudscraper and beautifulsoup
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot code
COPY bot.py .

# Run the bot
CMD ["python", "bot.py"]
