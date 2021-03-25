#!/usr/bin/env python
from diskstats import Diskstats
from datetime import timedelta
from glob import glob
from time import sleep
import argparse
import subprocess
import signal
import sys

# make it globalish
diskstats = None

def sigint_handler(sig, frame):
    print("Exiting ...")
    if diskstats is not None:
        diskstats.save()


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="daemon for running a sleeper tool to actually sleep the disks")
    parser.add_argument("--timeout", "-t", help="Time in minutes before timeout occurs and disks go to sleep (s)", default=25)
    parser.add_argument("--interval", "-i", help="Polling interval (s)", default=10)
    parser.add_argument("--filename", "-f", help="Filename to store temporary data, usefull if something crashes and you autorestart and do not want to lose the timeout time", default="data.json")
    parser.add_argument("--daemon", "-d", help="Make yourself angry and persistent", default=False, action="store_true")
    parser.add_argument("--verbose", "-v", help="Be verbose about it", default=False, action="store_true")

    # fetch all sdN from /dev
    disknames = [n.split("/")[-1] for n in glob("/dev/sd?")]

    # check smartctl version 7.2 and up. SAS spindown is included in this version
    smartctl = subprocess.run(['smartctl', '--version'], stdout=subprocess.PIPE).stdout.decode()
    if smartctl.split(" ")[1] < "7.2":
        print("Version 7.2 of smartctl or higher is required")
        exit(1)

    args = parser.parse_args()

    diskstats = Diskstats(filename=args.filename, disks=disknames, verbose=args.verbose)

    # start loop, check every n seconds
    while True and args.daemon:
        diskstats.update() # update timers
        diskstats.check_power() # check for sleepy mode
        stb = diskstats.set_standby(timeout=timedelta(minutes=args.timeout))
        if args.verbose:
            print("Disk Time idle       Last check")
            print(diskstats)
            print(stb)
        sleep(args.interval)

    if args.verbose:
        print("Disk Time idle      Last check")
        print(diskstats)
        diskstats.save()