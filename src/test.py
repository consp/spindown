from diskstats import Diskstats, Disk
from datetime import timedelta

d = Diskstats(filename="data.json", disks=['sda',
                                           'sdb',
                                           'sdc',
                                           'sdd',
                                           'sde',
                                           'sdf',
                                           'sdg',
                                           'sdh',
                                           'sdi',
                                           'sdj',
                                           'sdk',
                                           'sdl',
                                           'sdm',
                                           'sdn',
                                           'sdo',
                                           'sdp'])
d.update()
d.check_power()
d.set_standby(timeout=timedelta(minutes=30))
print(d)
d.save("data.json")
