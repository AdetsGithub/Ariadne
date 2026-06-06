FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

# Headed stealth requires a virtual framebuffer — WAFs flag --headless=new.
# Entrypoint wraps crawls with xvfb-run so Playwright can use headless=false.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ARIADNE_BROWSER_HEADLESS=false

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    fonts-liberation \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md SPEC.md ./
COPY docs ./docs
COPY ariadne ./ariadne
COPY engagements ./engagements
COPY scrapy.cfg ./

RUN pip install --no-cache-dir -e ".[browser]"

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["ariadne", "doctor"]
