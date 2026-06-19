# Diannot in a container. Includes headless Chromium so PDF/PNG export works.
FROM python:3.13-slim

# uv for dependency management.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies (the package builds from src, so copy it first).
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --no-dev

# Headless Chromium + its system libraries (used by the renderer for PDF/PNG).
RUN uv run playwright install --with-deps chromium

# Fonts are vendored inside the package, so rendering is fully offline.
# Bring your own Claude credentials at run time (ANTHROPIC_API_KEY) for AI features.
ENTRYPOINT ["uv", "run", "diannot"]
CMD ["--help"]
