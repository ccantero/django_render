#!/bin/bash

export SECRET_KEY=")s0s^5z1%gumm6xfg6x3!bqzc=y)-$7=flv%s!u-trx@+$#38f"
export CC_DEBUG="TRUE"
python manage.py migrate
python manage.py collectstatic --no-input
python manage.py runserver
