FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Create templates directory and copy files
COPY app/templates ./templates
COPY app/app.py .

EXPOSE 5000

CMD ["python", "app.py"]
