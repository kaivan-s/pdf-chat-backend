FROM python:3.7

RUN pip install Flask flask_cors firebase_admin langchain tempfile datetime gunicorn

COPY backend/ app/

WORKDIR /app

ENV PORT 8080

CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 app:app


