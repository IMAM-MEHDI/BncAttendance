# Use official Python image
FROM python:3.12-slim

# Set working directory to /app
WORKDIR /app

# Copy the backend folder and requirements
COPY backend/ /app/backend/
COPY backend/requirements.txt /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variable to ensure imports work from the backend directory
ENV PYTHONPATH=/app/backend

# Expose the port FastAPI runs on
EXPOSE 8000

# Command to run the application
# We run it from the backend directory so internal imports work
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
