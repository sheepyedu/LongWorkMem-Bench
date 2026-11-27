FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
WORKDIR /app
COPY tasks/__init__.py tasks/protocol.py ./tasks/
COPY tasks/s1/__init__.py tasks/s1/circuit.py tasks/s1/relay.py tasks/s1/engine.py ./tasks/s1/
COPY tasks/w1/__init__.py tasks/w1/claude.py tasks/w1/gateway.py ./tasks/w1/
USER 65534:65534
ENTRYPOINT ["python","-B","-u","-m","tasks.s1.engine"]
