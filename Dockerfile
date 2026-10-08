# Use uv's Python base image (matches pyproject requires-python >=3.13.7)
# Build for ARM64 with: docker build --platform linux/arm64 ...
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
 
WORKDIR /app
 
# Copy uv files
COPY pyproject.toml uv.lock ./
 
# Install dependencies (including strands-agents)
RUN uv sync --frozen --no-cache
 
# Copy agent file
COPY . .
 
# Expose port
EXPOSE 8080
 
# Run application
CMD ["uv", "run", "opentelemetry-instrument", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
 