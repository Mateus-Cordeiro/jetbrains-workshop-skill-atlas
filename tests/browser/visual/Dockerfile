FROM mcr.microsoft.com/playwright:v1.63.0-noble@sha256:eff16c30e6f3f4af0a03fa4b706120d5e9b0891c344a27d64559aff5900a4a27
RUN curl -fsSL --retry 3 https://github.com/astral-sh/uv/releases/download/0.9.8/uv-x86_64-unknown-linux-gnu.tar.gz -o /tmp/uv.tar.gz \
    && echo '950bad4899800ab158db97081b30a601a3ff4237d705756fda8695342cfcc20a  /tmp/uv.tar.gz' | sha256sum --check \
    && tar -xzf /tmp/uv.tar.gz --strip-components=1 -C /usr/local/bin uv-x86_64-unknown-linux-gnu/uv \
    && rm /tmp/uv.tar.gz
WORKDIR /work
ENV ATLAS_VISUAL_ENV=playwright-1.63.0-noble-amd64
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --python 3.13
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN uv sync --locked --python 3.13
CMD ["npm", "run", "test:visual"]
