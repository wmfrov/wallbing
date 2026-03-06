# Use an official Python runtime as the base image
FROM python:3.9

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed dependencies specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Optional: run every 6h inside the container (default is run-once for cron)
RUN chmod +x /app/entrypoint.sh

# Run once and exit (schedule via host cron for minimal resource use)
CMD ["python", "app.py"]
