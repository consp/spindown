# Introduction

Python tool to monitor /proc/diskstats for activity and spindown disks. Use with caution if you think 50k start stop and 600k loadcycles is way too little. Use with low timeout for saving polarbears.

# Legal stuff

Provided as-is. Damage to disks or other equipment is your own responsibility.

# Usage

```
usage: daemon.py [-h] [--timeout TIMEOUT] [--interval INTERVAL]
                 [--filename FILENAME] [--daemon] [--verbose]

daemon for running a sleeper tool to actually sleep the disks

optional arguments:
  -h, --help            show this help message and exit
  --timeout TIMEOUT, -t TIMEOUT
                        Time in minutes before timeout occurs and disks go to
                        sleep (s)
  --interval INTERVAL, -i INTERVAL
                        Polling interval (s)
  --filename FILENAME, -f FILENAME
                        Filename to store temporary data, usefull if something
                        crashes and you autorestart and do not want to lose
                        the timeout time
  --daemon, -d          Make yourself angry and persistent
  --verbose, -v         Be verbose about it
```

Modify the test.py file to play around.

Start with `daemon.py -d` in for example a screen session or create a startup script.
