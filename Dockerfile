# ensure python matches
FROM python:3.12.3

RUN mkdir /app
WORKDIR /app

# copy requiremnts
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
# copy 2 python scripts into /app dir
COPY iss_tracker.py test_iss_tracker.py /app/

# turn all files into executable
RUN chmod +rx /app/*.py
# sent environment path to /code dir
ENV PATH="/app:$PATH"

# default command to run iss_tracker.py
CMD ["python3", "iss_tracker.py"]
