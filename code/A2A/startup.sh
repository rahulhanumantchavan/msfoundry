#!/bin/bash
gunicorn -w 2 -k uvicorn.workers.UvicornWorker --bind=0.0.0.0:$PORT main:app