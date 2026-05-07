FROM python:3.12-slim

# Git commit hash passed at build time:
#   docker compose build --build-arg GIT_COMMIT=$(git rev-parse --short HEAD)
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Optional: noun-only search (pymorphy3)
ARG INSTALL_NOUN_SEARCH=false
RUN if [ "$INSTALL_NOUN_SEARCH" = "true" ]; then pip install --no-cache-dir pymorphy3; fi

# Copy source code
COPY src/ src/

# Create a non-root user
RUN useradd -m -u 1000 mcpuser && \
    chown -R mcpuser:mcpuser /app

USER mcpuser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV MCP_PORT=8003
ENV MCP_HOST=0.0.0.0

# Expose the MCP port
EXPOSE 8003

CMD ["python", "-m", "confluence_mcp.server"]
