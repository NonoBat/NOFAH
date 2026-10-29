FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1

RUN python -m pip install "mlflow==3.16.1" "psycopg[binary]"

EXPOSE 5000
