#!/bin/bash

source /home/jeremy/mdh-hockey/mdh.venv/bin/activate
python3 /home/jeremy/mdh-hockey/CapFriendly/main.py 2>&1 | mail -s "MDH CapFriendly Update `date`" jeremy.vercillo@gmail.com
deactivate
