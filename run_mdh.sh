#!/bin/bash

source /home/jeremy/mdh.venv/bin/activate
python3 /home/jeremy/mdh-hockey/mdhhockey/main.py 2>&1 | mail -s "MDH CapFriendly Update `date`" jeremy.vercillo@gmail.com
pip freeze > /home/jeremy/mdh-hockey/mdhhockey/requirements.txt
deactivate
