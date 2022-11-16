#!/bin/bash

export SECRET_KEY="MY_SECRET_KEY"
export CC_DEBUG="TRUE"
python manage.py migrate
python manage.py collectstatic --no-input
python manage.py runserver
