#!/bin/sh

#gunicorn --certfile /certs/tls.crt --keyfile /certs/tls.key  wkf:app -w 2 --threads 2 -b 0.0.0.0:5000
gunicorn wkf:app -w 4 --threads 2 -b 0.0.0.0:5000
