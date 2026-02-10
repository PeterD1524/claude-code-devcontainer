FROM archlinux:base-devel-20260208.0.488728

ARG CLAUDE_CODE_VERSION=latest

# Install basic development tools and iptables/ipset
RUN pacman --sync --sysupgrade --refresh --noconfirm
RUN pacman --remove --nodeps --nodeps --nosave --recursive --noconfirm iptables
RUN pacman --sync --sysupgrade --refresh --noconfirm bind dioxus-cli fish github-cli ipset iptables-nft jq jujutsu less man-db nodejs-lts-jod pnpm python python-playwright rustup typescript typescript-language-server uv vim
RUN echo -e 'y\n' | sudo pacman --sync --clean --clean

# Set `DEVCONTAINER` environment variable to help with orientation
ENV DEVCONTAINER=true

# Create workspace
RUN mkdir /workspace

WORKDIR /workspace

# Set up non-root user
RUN useradd --create-home arch
USER arch

# Install global packages
ENV PNPM_HOME=/home/arch/.local/share/pnpm
ENV PATH=$PATH:$PNPM_HOME

# Install Claude
RUN pnpm add --global @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

RUN rustup default stable
RUN rustup target add wasm32-unknown-unknown
RUN rustup component add rust-analyzer

# Copy and set up firewall script
COPY init-firewall.py /usr/local/bin/
USER root
RUN chmod +x /usr/local/bin/init-firewall.py && \
  echo "arch ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.py" > /etc/sudoers.d/arch-firewall && \
  chmod 0440 /etc/sudoers.d/arch-firewall
USER arch
USER root
