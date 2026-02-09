FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

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
EXPOSE 8000

# Run the server with SSE transport
CMD ["python", "-m", "confluence_mcp.server"]
