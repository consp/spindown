from datetime import datetime, timedelta
import json
from binascii import hexlify
import subprocess

class Diskstats:
    disks = {}
    filename = None
    verbose = False

    def __init__(self, filename=None, disks=None, verbose=False):
        self.disks = {}
        self.verbose = verbose
        if filename is not None:
            self.load(filename)

        if disks is None:
            self.update(reload=True)
        else:
            for disk in disks:
                if disk not in self.disks:
                    self.disks[disk] = Disk(disk)
                self.disks[disk].update()

    def update(self, reload=False):
        with open('/proc/diskstats', 'r') as f:
            for line in f.readlines():
                data = line[13:].split(' ')
                if data[0] not in self.disks and reload:
                    self.disks[data[0]] = Disk(data[0])
                elif data[0] in self.disks:
                    self.disks[data[0]].update()

    def load(self, filename):
        try:
            self.filename = filename
            with open(filename, "r") as f:
                data = json.loads(f.read())

                for name, value in data.items():
                    self.disks[name] = Disk(name,
                                            timestamp=value['time_last_check'],
                                            current_reads_completed=value['current_reads_completed'],  # noqa
                                            current_writes_completed=value['current_writes_completed'])  # noqa
        except FileNotFoundError:
            if self.verbose:
                print("Failed to find file, assuming you make it when closing")
            pass

    def save(self, filename=None):
        if filename is None:
            filename = self.filename

        if filename is None:
            raise ValueError("Need a filename to store the data")
        data = {}
        for name, disk in self.disks.items():
            data[name] = {
                'time_last_check': datetime.timestamp(disk.time_last_check),
                'current_reads_completed': disk.current_reads_completed,
                'current_writes_completed': disk.current_writes_completed
            }
        with open(filename, "w") as f:
            f.write(json.dumps(data))

    def check_power(self):
        for name, disk in self.disks.items():
            disk.powerstatus()

    def set_standby(self, timeout=timedelta(minutes=25)):
        s = "Setting disks in standby:\n"
        for name, disk in self.disks.items():
            r = disk.standby(timeout=timeout)
            s = s + "%-4s " % (name) + r + "\n"
        return s

    def __repr__(self):
        return str(self)

    def __str__(self):
        s = ""
        for disk in self.disks:
            s += str(self.disks[disk]) + "\n"
        return s


class Disk:
    fields = [
        'reads_completed',
        'reads_merged',
        'sectors_read',
        'time_reading',
        'writes_completed',
        'writes_merged',
        'sectors_written',
        'time_writing',
        'ios_in_progress',
        'time_ios',
        'time_ios_weighted',
        'discards_completed',
        'discards_merged',
        'sectors_discarded',
        'time_discarding',
        # 'flush_requests_completed',
        # 'time_flushing'
    ]

    current_reads_completed = 0
    current_writes_completed = 0

    time_last_check = 0
    status = "UNKNOWN"

    def __init__(self, name, timestamp=None, current_reads_completed=0, current_writes_completed=0):  # noqa
        # name is the drivename, data is the raw input from diskstats
        self.time_idle = 0
        self.time_last_check = datetime.utcnow() if timestamp is None else datetime.fromtimestamp(timestamp)  # noqa
        self.current_reads_completed = current_reads_completed
        self.current_writes_completed = current_writes_completed
        self.name = name
        self.update()

    def update(self):
        with open('/proc/diskstats', 'r') as f:
            for line in f.readlines():
                diskdata = line[13:].split(' ')
                if diskdata[0].strip() == self.name:
                    data = diskdata[1:]

                    if len(data) != len(self.fields):
                        raise ValueError("Number of fields does not match data input, kernel update?")  # noqa

                    for i in range(0, len(data)):
                        setattr(self, self.fields[i], int(data[i]))

                    if self.reads_completed > self.current_reads_completed:
                        self.time_last_check = datetime.utcnow()
                    if self.writes_completed > self.current_writes_completed:
                        self.time_last_check = datetime.utcnow()

                    self.current_reads_completed = self.reads_completed
                    self.current_writes_completed = self.writes_completed

    def idle(self):
        return datetime.utcnow() - self.time_last_check

    def __lt__(self, other):
        return self.time_last_check < other.time_last_check

    def __gt__(self, other):
        return self.time_last_check > other.time_last_check

    def __eq__(self, other):
        return self.time_last_check == other.time_last_check

    def __str__(self):
        return "%-4s %-14s %s" % (self.name,
                                  datetime.utcnow() - self.time_last_check,  # noqa
                                  self.time_last_check)

    def __repr__(self):
        return str(self)

    def powerstatus(self):
        data = subprocess.run(['smartctl', '-n', 'standby', '-i', '/dev/%s' % self.name], stdout=subprocess.PIPE).stdout.decode()
        if 'Device is in ' in data:
            self.status = data.split("Device is in ")[1].split(" mode")[0]
        return self.status

    def standby(self, timeout=timedelta(minutes=25)):
        # sas is STANDBY xxxxxxxxxx (by command/timer)
        # sata is STANDBY
        if self.idle() > timeout and "STANDBY" not in self.status:
            data = subprocess.run(['smartctl', '-s', 'standby,now', '/dev/%s' % self.name], stdout=subprocess.PIPE).stdout
            return "Standby issued"
        elif "STANDBY" in self.status and self.idle() > timeout:
            return "Timer triggered but disk already in standby mode"
        elif "STANDBY" in self.status:
            return "Disk in standby but timer not triggered"



