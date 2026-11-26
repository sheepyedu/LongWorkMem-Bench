FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
WORKDIR /league
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY __init__.py game.py table.py ./s1/
ENTRYPOINT ["python", "-m", "s1.table"]
