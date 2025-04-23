FROM python:3.12-slim

RUN apt-get update && apt-get install -y python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /sandbox
RUN python3 -m venv venv
ENV PATH="/sandbox/venv/bin:$PATH"

COPY ./python/mentis_executor/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY ./python/mentis_executor ./mentis_executor
COPY ./python/mentis_client ./mentis_client

WORKDIR /work

CMD ["uvicorn", "mentis_executor.main:app", "--host=0.0.0.0", "--app-dir=/sandbox", "--port=8000"]
