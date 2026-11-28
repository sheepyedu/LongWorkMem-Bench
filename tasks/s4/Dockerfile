FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
WORKDIR /app
ARG ENGINE_REV=ecf931181b9a65bb4116a2153fb78c16f1438e00
RUN python -c 'from urllib.request import urlretrieve; import sys; urlretrieve("https://codeload.github.com/bcollazo/catanatron/tar.gz/"+sys.argv[1], "/tmp/engine.tar.gz")' "$ENGINE_REV" \
    && echo '1fa3a655363b89b6db54b58d379945596428713ccece1501912a68bcc2979350  /tmp/engine.tar.gz' | sha256sum -c - \
    && mkdir /opt/catanatron && tar -xzf /tmp/engine.tar.gz -C /opt/catanatron --strip-components=1 "catanatron-${ENGINE_REV}/catanatron/catanatron" "catanatron-${ENGINE_REV}/LICENSE" \
    && rm /tmp/engine.tar.gz
RUN python -c 'from urllib.request import urlretrieve; urlretrieve("https://codeload.github.com/networkx/networkx/tar.gz/refs/tags/networkx-3.7", "/tmp/networkx.tar.gz")' \
    && echo '41b53397dd99965dce78feefe320b493b135ab883e18a8f93b14e8c1387e8a50  /tmp/networkx.tar.gz' | sha256sum -c - \
    && mkdir /opt/networkx && tar -xzf /tmp/networkx.tar.gz -C /opt/networkx --strip-components=1 networkx-networkx-3.7/networkx networkx-networkx-3.7/LICENSE.txt \
    && rm /tmp/networkx.tar.gz
ENV PYTHONPATH=/opt/catanatron/catanatron:/opt/networkx
COPY __init__.py arena.py bots.py continuation-board.json engine.py fixtures.json league.py public.py /app/tasks/s4/
USER 65534:65534
ENTRYPOINT ["python","-B","-u","-m","tasks.s4.engine"]
