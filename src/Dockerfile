FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    streamlit==1.66.1 plotly==7.1.0 pandas==2.2.3 pyarrow==20.0.0 boto3

COPY app.py .

EXPOSE 8080
CMD ["streamlit", "run", "app.py", \
     "--server.port=8080", "--server.address=0.0.0.0", "--server.headless=true"]