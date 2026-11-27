FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
WORKDIR /app
COPY benchmark_protocol.py .
COPY s1/__init__.py s1/circuit.py s1/relay.py s1/engine.py ./s1/
COPY w1/__init__.py w1/claude.py w1/gateway.py ./w1/
USER 65534:65534
ENTRYPOINT ["python","-B","-u","-m","s1.engine"]
