import sgio
import struct
from binascii import unhexlify, hexlify
import json
import subprocess
from enum import Enum, IntEnum


class LedMode:
    OFF = "off"
    SLOW =  "rebuild"
    FAST = "locate"
    ON = "failure"



class PowerCondition:
    #sas
    IDLE_A = (0x2, 0x0)
    IDLE_B = (0x2, 0x1)
    IDLE_C = (0x2, 0x2)
    STANDBY_Y = (0x3, 0x1)
    STANDBY_Z = (0x3, 0x0)
    LU_CONTROL = (0x7, 0x0)
    IDLE_A_FORCE = (0xA, 0x0)
    IDLE_B_FORCE = (0xA, 0x1)
    IDLE_C_FORCE = (0xA, 0x2)
    STANDBY_Y_FORCE = (0xB, 0x1)
    STANDBY_Z_FORCE = (0xB, 0x0)

    #sas
    IDLE_IMMEDIATE = "--idle-immediate"
    IDLE_UNLOAD = "--idle-unload"
    STANDBY = "-y"
    SLEEP = "-Y"

    @classmethod
    def set(cls, disktype, state, force=False):
        if isinstance(disktype, SAS):
            if state == PowerState.IDLE_A:
                return cls.IDLE_A_FORCE if force else cls.IDLE_A
            elif state == PowerState.IDLE_B:
                return cls.IDLE_B_FORCE if force else cls.IDLE_B
            elif state == PowerState.IDLE_C:
                return cls.IDLE_C_FORCE if force else cls.IDLE_C
            elif state == PowerState.STANDBY_Y:
                return cls.STANDBY_Y_FORCE if force else cls.STANDBY_Y
            elif state == PowerState.STANDBY_Z:
                return cls.STANDBY_Z_FORCE if force else cls.STANDBY_Z
        elif isinstance(disktype, SATA):
            if state == PowerState.IDLE_A:
                return cls.IDLE_IMMEDIATE
            elif state == PowerState.IDLE_B or state == PowerState.IDLE_C:
                return cls.IDLE_UNLOAD
            elif state == PowerState.STANDBY_Y or state == PowerState.STANDBY_Z:
                return cls.STANDBY
            # sleep is not used
        return None

class PowerState(IntEnum):
    ACTIVE = 0
    IDLE_A = 1
    IDLE_B = 2
    IDLE_C = 3
    STANDBY_Y = 4
    STANDBY_Z = 5


class Generic:
    name = None
    devicename = None
    path = None

    vendor = None
    serial = None
    product = None

    port = None
    port_speed = None
    port_type = None
    interface = None

    debug = True
    disco = False

    recovery_time = {
        'stopped': 0,
        'standby_z': 0,
        'standby_y': 0,
        'idle_a': 0,
        'idle_b': 0,
        'idle_c': 0
    }

    idle_a_en = 0
    idle_b_en = 0
    idle_c_en = 0
    standby_y_en = 0
    standby_z_en = 0
    idle_a_timer = 0
    idle_b_timer = 0
    idle_c_timer = 0
    standby_y_timer = 0
    standby_z_timer = 0

    powerstate = PowerState.ACTIVE # keep track for idle

    def __init__(self, name, path=None, debug=False, disco=False):
        self.name = name
        self.path = path if path is not None else "/dev/" + name
        self.devicename = self.path.split("/")[-1]
        self.debug = debug
        self.disco = disco
        if self.debug:
            print("Device %s, %s" % (self.name, self.path))

        self._get_serial()
        self._get_recovery_time()
        self._get_link()
        self._get_power_control()

    def is_scsi(self):
        return False

    def is_sata(self):
        return False

    def _get_serial(self):
        raise NotImplementedError

    def _get_link(self):
        raise NotImplementedError

    def get_recovery_time(self):
        raise NotImplementedError

    def _power_set(self):
        raise NotImplementedError

    def _power_state(self):
        raise NotImplementedError

    def _rate(self):
        raise NotImplementedError

    def rate(self):
        return self._rate()

    def power_set(self, state, force=False):
        self._power_set(state, force=force)
        self.power_state()
        if self.disco:
            if self.powerstate == PowerState.IDLE_B:
                self.blink(mode=LedMode.SLOW)
            elif self.powerstate == PowerState.IDLE_C or self.powerstate == PowerState.STANDBY_Y:
                self.blink(mode=LedMode.FAST)
            elif self.powerstate == PowerState.STANDBY_Z:
                self.blink(mode=LedMode.ON)
            else:
                self.blink(mode=LedMode.OFF)

    def power_state(self):
        return self._power_state()

    def _led(self, mode=LedMode.OFF):
        # for now just use ledctl
        subprocess.run(['ledctl', '--listed-only', mode + "=" + self.path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def blink(self, mode=LedMode.OFF):
        self._led(mode=mode)



class SAS(Generic):
    address = None

    def __init__(self, name, path=None, debug=False, disco=False):
        super(SAS, self).__init__(name, path=path, debug=debug, disco=disco)

    def _rate(self):
        if self.port_speed is None:
            self._get_link()

        if self.port_speed == 0x08:
            return "1.5 Gb/s"
        elif self.port_speed == 0x09:
            return "3 Gb/s"
        elif self.port_speed == 0x0A:
            return "6 Gb/s"
        elif self.port_speed == 0x0B:
            return "12 Gb/s"
        return "? Gb/s"

    def is_scsi(self):
        return True

    def _raw_cmd(self, cmd, data, length=32):

        with open(self.path, "rb") as f:
            length = min(length + 32, 255)
            rv = bytearray(length)
            rv_length = sgio.execute(f, cmd, data, rv, max_sense_data_length=length)
            if self.debug:
                print("Received: [%d] %s" % (rv_length, hexlify(rv[:rv_length])))
            return rv[:rv_length]

    def _inquiry(self, evpd, page, length):
        cmd = unhexlify("12%02X%02X%04X00" % (evpd, page, length))
        if self.debug:
            print(hexlify(cmd))
        data = self._raw_cmd(cmd, None, 255)
        return data[:length]

    def _log_sense(self, page, subpage, length):
        cmd = unhexlify("4D00%02X%02X000000%04X00" % (page | 0b01000000, subpage, length))
        if self.debug:
            print(hexlify(cmd))
        data = self._raw_cmd(cmd, None, 255)
        return data[:length]

    def _mode_sense(self, pc, page, subpage, length):
        # pc 0 = current value
        # pc 1 = changable values
        # pc 2 = default value
        # pc 3 = saved value
        pc = pc << 6
        cmd = unhexlify("1A00%02X%02X%02X00" % (page | pc, subpage, length))
        if self.debug:
            print(hexlify(cmd))
        data = self._raw_cmd(cmd, None, 255)
        return data[:length]

    def _request_sense(self):
        cmd = unhexlify("030000002000")
        if self.debug:
            print(hexlify(cmd))
        data = self._raw_cmd(cmd, None, 32)
        return data

    def _send_diagnostics(self, fc, pf, pl):
        fc = (fc << 6) & 0b11000000
        pf = (pf << 4) & 0b00010000
        cmd = unhexlify("1D%02X00%04X00" % (fc | pf, pl & 0xFFFF))
        if self.debug:
            print(hexlify(cmd))
        data = self._raw_cmd(cmd, None, 255)
        return data[:length]

    def _get_serial(self):
        data = self._inquiry(0, 0, 44)

        self.vendor = vendor = data[8:16].strip(b" ").decode()
        self.product = product_id = data[16:32].strip(b" ").decode()
        revision = data[32:36].decode()
        self.serial = serial = data[36:44].decode()
        if self.debug:
            print(vendor, product_id, revision, serial)

    def _get_recovery_time(self):
        data = self._inquiry(1, 0x8a, 18)
        if self.debug:
            print(data)
            print(hexlify(data))
        idle_a_s = data[5] & 0b00000001
        idle_b_s = data[5] & 0b00000010
        idle_c_s = data[5] & 0b00000100
        standby_y_s = data[4] & 0b00000010
        standby_z_s = data[4] & 0b00000001
        self.recovery_time['idle_a'] = struct.unpack(">H", data[12:14])[0] / 1000.0 if idle_a_s else -1
        self.recovery_time['idle_b'] = struct.unpack(">H", data[14:16])[0] / 1000.0 if idle_b_s else -1
        self.recovery_time['idle_c'] = struct.unpack(">H", data[16:18])[0] / 1000.0 if idle_c_s else -1
        self.recovery_time['standby_y'] = struct.unpack(">H", data[10:12])[0] / 1000.0 if standby_y_s else -1
        self.recovery_time['standby_z'] = struct.unpack(">H", data[10:12])[0] / 1000.0 if standby_z_s else -1
        self.recovery_time['stopped'] = struct.unpack(">H", data[6:8])[0] / 1000.0

        if self.debug:
            print(self.recovery_time)

    def _get_power_control(self):
        data = self._mode_sense(0, 0x1a, 0x00, 0x26)
        # 12
        pm_bg = (0b11000000 & data[14]) >> 6
        self.standby_y_en = 0b00000001 & data[14]
        self.standby_z_en = 0b00000001 & data[15]
        self.idle_c_en = (0b00001000 & data[15]) >> 3
        self.idle_b_en = (0b00000100 & data[15]) >> 2
        self.idle_a_en = (0b00000010 & data[15]) >> 1
        self.idle_a_timer = struct.unpack(">I", data[16:20])[0]
        self.standby_z_timer = struct.unpack(">I", data[20:24])[0]
        self.idle_b_timer = struct.unpack(">I", data[24:28])[0]
        self.idle_c_timer = struct.unpack(">I", data[28:32])[0]
        self.standby_y_timer = struct.unpack(">I", data[32:36])[0]

        if self.debug:
            print("IDLE_A: %d %d" % (self.idle_a_en, self.idle_a_timer))
            print("IDLE_B: %d %d" % (self.idle_b_en, self.idle_b_timer))
            print("IDLE_C: %d %d" % (self.idle_c_en, self.idle_c_timer))
            print("STBY_Y: %d %d" % (self.standby_y_en, self.standby_y_timer))
            print("STBY_Y: %d %d" % (self.standby_z_en, self.standby_z_timer))

    def _get_link(self):
        data = self._log_sense(0x18, 0x00, 0xd8)
        phy_port = struct.unpack(">H", data[4:6])[0]
        phy_nr = data[11]
        self.port_type = phy_type = (data[16] & 0b01110000) >> 4
        # port type is not usefull in our sense
        self.port_speed = phy_rate = data[17] & 0b00001111
        if phy_rate == 0x8:
            self.port_type = "SAS"
        elif phy_rate == 0x9:
            self.port_type = "SAS1"
        elif phy_rate == 0xA:
            self.port_type = "SAS2"
        elif phy_rate == 0xB:
            self.port_type = "SAS3"
        self.address = address = data[20:28]

        if self.debug:
            print("Port: %d %d %d %02X" % (phy_port, phy_nr, phy_type, phy_rate))
            print("Address: %s" % (hexlify(address).decode()))


    def _set_start_stop(self, pc, pm):
        cmd = unhexlify("1B00000%1X%1X000" % (pm, pc))
        if self.debug:
            print(hexlify(cmd))
        data = self._raw_cmd(cmd, None, 32)
        return data

    def _power_state(self):
        data = self._request_sense()
        code = data[12]
        q = data[13]
        if code == 0 and q == 0:
            return PowerState.ACTIVE
        if code == 0x5e:
            if q == 1 or q == 3:
                self.powerstate = PowerState.IDLE_A
            elif q == 2 or q == 4:
                self.powerstate = PowerState.STANDBY_Z
            elif q == 5 or q == 6:
                self.powerstate = PowerState.IDLE_B
            elif q == 7 or q == 8:
                self.powerstate = PowerState.IDLE_C
            elif q == 9 or q == 10:
                self.powerstate = PowerState.STANDBY_Y
            else:
                self.powerstate = PowerState.ACTIVE
        return self.powerstate

    def _power_set(self, state, force=False):
        pc, pm = PowerCondition.set(self, state, force=force)
        self._set_start_stop(pc, pm)
        self.powerstate_set = state
        self._power_state() # verify
        if self.debug:
            print("State requested: %s, set to %s" % (self.powerstate_set, self.powerstate))




class SATA(Generic):
    ## Uses hdparm instead of direct sgio commands
    ## ATA is a ****fest and full if pitfalls and dead ends
    ## idle_a is idle immediate
    ## idle_b is idle immediate unload
    ## idle_c == standby_y is standby
    ## standby_z is standby, sleep is power off will not use

    powerstate_set = PowerState.ACTIVE

    def __init__(self, name, path=None, debug=False, disco=False):
        super(SATA, self).__init__(name, path=path, debug=debug, disco=disco)


    def _power_state(self):
        mode = self._cmd_hdparm(operants=['-C'])
        if "active" in mode:
            # all idle modes report this as well as active, assume it went into mode we set
            self.powerstate = self.powerstate_set if self.powerstate_set is not None else PowerState.ACTIVE
        elif "standby" in mode:
            self.powerstate = PowerState.STANDBY_Z
        else:
            self.powerstate = PowerState.ACTIVE
        return self.powerstate

    def _power_set(self, state, force=False):
        self._cmd_hdparm(operants=[PowerCondition.set(self, state)])
        self.powerstate_set = state
        self._power_state() # verify
        if self.debug:
            print("State requested: %s, set to %s" % (self.powerstate_set, self.powerstate))

    def is_sata(self):
        return True

    def _get_serial(self):
        data = self._cmd_smartctl(operants=['-x'])
        self.vendor = data['model_family'] if 'model_family' in data else ''
        self.serial = data['serial_number'] if 'serial_number' in data else ''
        self.product = data['model_name'] if 'model_name' in data else ''

    def _get_recovery_time(self):
        pass

    def _get_link(self):
        data = self._cmd_smartctl(operants=['-x'])
        self.port_speed = data['interface_speed']['current']['units_per_second'] / 10.0 if 'interface_speed' in data else 0
        self.port_type = data['sata_version']['string'] if 'sata_version' in data else ''

    def _rate(self):
        if self.port_speed is None:
            self._get_link()

        return "%.1f Gb/s" % (self.port_speed)

    def _get_power_control(self):
        pass

    def _cmd_hdparm(self, operants=[]):
        return subprocess.run(['hdparm'] + operants + [self.path], stdout=subprocess.PIPE).stdout.decode()

    def _cmd_smartctl(self, operants=[]):
        return json.loads(subprocess.run(['smartctl', '--json', '--nocheck=standby', self.path] + operants, stdout=subprocess.PIPE).stdout.decode())

