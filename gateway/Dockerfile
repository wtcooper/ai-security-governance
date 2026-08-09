# Bundled LiteLLM gateway.
#
# Separate image from the backend on purpose: `litellm[proxy]` requires boto3>=1.43.1 while
# `inspect-ai` requires aioboto3, which caps boto3<1.40.62. They cannot share a venv.
#
# The version floor is a security control, not a preference: litellm 1.82.7 and 1.82.8 were
# malicious releases (TeamPCP PyPI compromise, 2026-03-24) that shipped a .pth payload
# executing on every Python process start. Safe ranges are <=1.82.6 or >=1.83.0.
FROM python:3.12-slim

WORKDIR /gateway

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY litellm_config.yaml mock_handlers.py ./

# No default for GATEWAY_API_KEY. Baking one into the image gives every copy of it the same
# known bearer token, and compose publishes this service on all interfaces — so a shipped
# default is a credential anyone on the network already knows. start_proxy.sh supplies a
# development value; a deployment must set its own.
ENV OLLAMA_API_BASE=http://host.docker.internal:11434

EXPOSE 4000

# Config path is absolute; cwd is /gateway so `mock_handlers` resolves as a top-level module.
CMD ["litellm", "--config", "/gateway/litellm_config.yaml", "--port", "4000", "--num_workers", "1"]
