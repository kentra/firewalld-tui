FROM almalinux:latest

ENV container=docker

# Install firewalld and core dependencies (conntrack-tools + iproute feed
# the dashboard/monitor samplers; NET_ADMIN is granted in docker-compose.yml)
RUN dnf -y install \
    firewalld \
    dbus \
    dbus-daemon \
    python3 \
    python3-pip \
    python3-devel \
    gcc \
    conntrack-tools \
    iproute \
    && dnf clean all

# Install the TUI package
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip3 install --no-cache-dir .

# Copy the container start script
COPY scripts/docker-start.sh /docker-start.sh
RUN chmod +x /docker-start.sh

# Copy the smoke test
COPY scripts/smoke_test.py /app/scripts/smoke_test.py

ENTRYPOINT ["/docker-start.sh"]
CMD ["bash"]
