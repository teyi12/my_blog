#!/bin/bash

# Build and run the Docker container locally

docker build -t blog1-app .
docker run -p 8000:8000 --env-file .env blog1-app
