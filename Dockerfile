# Use official Python image
FROM python:3.12-slim

# Set working directory to /app
WORKDIR /app

# Copy the backend requirements first for caching
COPY backend/requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire backend folder content into the current WORKDIR (/app)
COPY backend/ .

# Expose the default port
EXPOSE 8000

# Command to run the application
# We use the PORT environment variable provided by Render
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
