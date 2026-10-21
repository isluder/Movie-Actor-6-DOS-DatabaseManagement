FROM docker.io/library/python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY src/requirements.txt /tmp/runtime-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/runtime-requirements.txt
CMD ["python", "-m", "flask", "--app", "src.app:create_app", "run", "--host", "0.0.0.0"]

FROM runtime AS notebook
COPY requirements-notebook.txt /tmp/notebook-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/notebook-requirements.txt
CMD ["python", "check_environment.py"]
