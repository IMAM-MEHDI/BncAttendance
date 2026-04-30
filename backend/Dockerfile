# Use official Python image
FROM python:3.12-slim

# Set working directory to /app
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files from the current folder (which will be the backend folder)
COPY . .

# Expose the default port
EXPOSE 7860

# Command to run the application
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
