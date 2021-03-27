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

    def set_standby(self, standby_timeout=timedelta(minutes=60)):
        s = "Setting disks in standby:\n"
        for name, disk in self.disks.items():
            r = disk.standby(standby_timeout=standby_timeout)
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
    sata = False
    sas = False
    staged = False

    def __init__(self, name, timestamp=None, current_reads_completed=0, current_writes_completed=0):  # noqa
        # name is the drivename, data is the raw input from diskstats
        self.time_idle = 0
        self.time_last_check = datetime.utcnow() if timestamp is None else datetime.fromtimestamp(timestamp)  # noqa
        self.current_reads_completed = current_reads_completed
        self.current_writes_completed = current_writes_completed
        self.name = name
        self.sas = False
        self.sata = False
        self.check_protocol()
        self.update()
        self.staged = False

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

                    if self.reads_completed > self.current_reads_completed or self.ios_in_progress != 0:
                        self.time_last_check = datetime.utcnow()
                    if self.writes_completed > self.current_writes_completed or self.ios_in_progress != 0:
                        self.time_last_check = datetime.utcnow()

                    self.current_reads_completed = self.reads_completed
                    self.current_writes_completed = self.writes_completed

    def idle(self):
        return datetime.utcnow() - self.time_last_check

    def check_protocol(self):
        data = subprocess.run(['smartctl', '-i', '/dev/%s' % self.name], stdout=subprocess.PIPE).stdout
        if b"Transport protocol" in data:
            self.sata = False
            self.sas = True
        else:
            self.sata = True
            self.sas = False

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
        elif "Power mode is" in data:
            self.status = data.split("Power mode is:")[1].strip()
        elif "Power mode was" in data:
            self.status = data.split("Power mode was:")[1].strip()
        else:
            self.status = "UNKNOWN"
        return self.status

    def standby(self, standby_timeout=timedelta(minutes=60), idle_c_timeout=timedelta(minutes=30), idle_b_timeout=timedelta(minutes=10), idle_a_timeout=timedelta(seconds=60)):
        # sas is STANDBY xxxxxxxxxx (by command/timer)
        # sata is STANDBY
        # IDLE_b can be use to force, idle usually works. Idle_c == standby_y in my case
        if self.idle() > standby_timeout and "STANDBY" not in self.status:
            if self.staged:
                data = subprocess.run(['smartctl', '-s', 'standby,now', '/dev/%s' % self.name], stdout=subprocess.PIPE).stdout
                self.staged = False
                return "STANDBY_Z issued"
            else:
                self.staged = True
                return "STANDBY_Z Staged"
        elif self.idle() > idle_c_timeout and "STANDBY" not in self.status and "IDLE_C" not in self.status and not self.sata and "ACTIVE" not in self.status:
            if self.staged:
                data = subprocess.run(['sg_start', '-r', '-p2', '-m2', '/dev/%s' % self.name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout
                self.staged = False
                return "IDLE_C Issued"
            else:
                self.staged = True
                return "IDLE_C Staged"
        elif self.idle() > idle_b_timeout and "STANDBY" not in self.status and "IDLE_C" not in self.status and "IDLE_" not in self.status and not self.sata and "ACTIVE" not in self.status:
            if self.staged:
                data = subprocess.run(['sg_start', '-r', '-p2', '-m1', '/dev/%s' % self.name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout
                self.staged = False
                return "IDLE_B Issued"
            else:
                self.staged = True
                return "IDLE_B Staged"
        elif self.idle() > idle_a_timeout and "ACTIVE" in self.status and not self.sata:
            if self.staged:
                data = subprocess.run(['sg_start', '-r', '-p2', '-m0', '/dev/%s' % self.name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout
                self.staged = False
                return "IDLE_A Issued"
            else:
                self.staged = True
                return "IDLE_A Staged"
        elif "STANDBY" in self.status and self.idle() < standby_timeout:
            return "Disk in standby but timer not triggered"
        elif "IDLE_C" in self.status and self.idle() < idle_c_timeout:
            return "Disk in idle_c but timer not triggered"
        elif "IDLE_" in self.status and self.idle() < idle_b_timeout:
            return "Disk in idle_b but timer not triggered"
        elif "IDLE" in self.status and self.idle() < idle_a_timeout and "ACTIVE" not in self.status:
            return "Disk in idle_a but timer not triggered"
        return "Disk in %s mode" % (self.status)



