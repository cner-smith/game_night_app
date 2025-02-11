# game_night_app/Dockerfile

# Use the specified Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container
COPY . /app

# Install required Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Install cron and clean up package lists to reduce image size
RUN apt-get update && apt-get install -y cron && apt-get clean && rm -rf /var/lib/apt/lists/*

# Add the cron job for updating BoardGameGeek data
RUN echo "0 3 * * * cd /app && /usr/local/bin/python3 fetch_bgg_data.py >> /app/logs/cron.log 2>&1" > /etc/cron.d/bgg-cron

# Set permissions for the cron job
RUN chmod 0644 /etc/cron.d/bgg-cron

# Apply the cron job
RUN crontab /etc/cron.d/bgg-cron

# Create the log file and ensure the logs directory exists
RUN mkdir -p /app/logs && touch /app/logs/cron.log

# Expose port 8000 for the Flask app
EXPOSE 8000

# Set environment variable for Flask
ENV FLASK_APP=app:app

# Run cron in the background and the Flask app
CMD ["sh", "-c", "cron && flask run --host=0.0.0.0 --port=8000"]
