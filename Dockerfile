# Reviewer demo image: builds the synthetic demo data and serves the web application on port 5002.
#   docker build -t webrulebench .
#   docker run --rm -p 5002:5002 webrulebench
# The login token is printed at start-up (also in /app/demo/data/REVIEWER_LOGIN.txt).
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .
ENV WRB_HOST=0.0.0.0 WRB_DEBUG=0
EXPOSE 5002
CMD ["webrulebench", "demo", "--rebuild", "--port", "5002"]
