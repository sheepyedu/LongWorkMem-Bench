FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-calc \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir openpyxl==3.1.5 et-xmlfile==2.0.0
# The office runs under the host UID and a read-only root. Give Calc a per-command profile.
RUN sed -i 's|^UserInstallation=.*|UserInstallation=file:///tmp/office-calc-profile|' /usr/lib/libreoffice/program/bootstraprc
WORKDIR /office
