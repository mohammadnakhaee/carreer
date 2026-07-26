# career-ops Streamlit GUI — dashboard / tracker / report viewer.
#
# This image contains only the Python runtime + deps. Your data (cv.md, config/,
# data/, reports/, output/, modes/) is bind-mounted at runtime so it lives on the
# host and persists — see docker-compose.yml.
#
# NOTE: The "Pipeline runner" and "Draft answers" buttons shell out to the
# `claude` CLI, which is NOT installed here. Those features are inert in this
# image; everything else (tracking, reports, downloads, cleanup) works. See the
# "Full mode" notes in the deploy docs to add the CLI + auth.
FROM python:3.12-slim

WORKDIR /app

# Install Python deps first so this layer caches across code changes.
COPY streamlit_app/requirements.txt ./streamlit_app/requirements.txt
RUN pip install --no-cache-dir -r streamlit_app/requirements.txt

# App code. When docker-compose bind-mounts the project over /app, the host copy
# wins; this COPY keeps the image runnable on its own (data still needs mounting).
COPY streamlit_app/ ./streamlit_app/

EXPOSE 8501

# Streamlit must bind 0.0.0.0 inside a container; --headless skips the browser
# launch and the first-run email prompt. The app re-syncs static/output on every
# render, so no boot-time sync step is needed here.
CMD ["streamlit", "run", "streamlit_app/app.py", \
     "--server.enableStaticServing=true", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
