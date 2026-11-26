FROM python:3.12-slim
RUN pip install --no-cache-dir openpyxl==3.1.5
WORKDIR /office
