# --- Base Image ---
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Use a more stable mirror
RUN sed -i 's|http://archive.ubuntu.com|http://mirrors.edge.kernel.org|g' /etc/apt/sources.list

# --- Install System Dependencies ---
RUN apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        wget \
        ca-certificates \
        libgomp1 \
        libx11-6 \
    && rm -rf /var/lib/apt/lists/*

# --- Install Python Dependencies ---
RUN pip3 install --no-cache-dir google-cloud-storage

# --- Download and Install EnergyPlus ---
ENV ENERGYPLUS_VERSION=22.1.0 \
    ENERGYPLUS_TAG=v22.1.0 \
    ENERGYPLUS_SHA=ed759b17ee

# RUN wget -q "https://github.com/NREL/EnergyPlus/releases/download/${ENERGYPLUS_TAG}/EnergyPlus-${ENERGYPLUS_VERSION}-${ENERGYPLUS_SHA}-Linux-Ubuntu20.04-x86_64.sh" \
RUN wget -q "https://github.com/NatLabRockies/EnergyPlus/releases/download/v22.1.0/EnergyPlus-22.1.0-ed759b17ee-Linux-Ubuntu20.04-x86_64.sh" \
        -O /tmp/ep_installer.sh \
    && chmod +x /tmp/ep_installer.sh \
    && echo "y\n" | /tmp/ep_installer.sh \
    && rm /tmp/ep_installer.sh

# --- Set Up App ---
WORKDIR /app
COPY run_simulation.py .

# --- Default Command ---
CMD ["python3", "run_simulation.py"]