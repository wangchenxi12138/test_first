#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Blueprint, not finished yet.

>>>
>>> client = adb.Client(host='127.0.0.1', port=5037)
>>> client.devices()
# {'EP7333W7XB': 'device'}
>>> client.version()
# 1.0.32
>>> client.connect('10.0.0.1', 5555)
True
>>> client.disconnect('10.0.0.1:5555')
True
>>>
>>> dev = client.device(serial=None)
>>> dev.packages()
[{'name': 'com.example.demo', 'version': 2}]
>>> dev.forward_list()
[{'local': 'tcp:8001', 'remote': 'tcp:8000'}]
>>> dev.properties()
{'ro.build.brand', 'MI2', ...}
>>> dev.install('demo.apk')
True
>>> dev.uninstall('com.example.demo', keep_data=True)
True
>>> dev.logcat() # TODO
>>> dev.pull('/data/local/tmp/_screen.png', './')
True
>>> dev.push('./demo.apk', '/data/local/tmp/demo.apk')
True
>>> dev.listdir('/data/local/tmp')
['_screen.png']
>>> dev.shell('ls', '-l', '/data/local/tmp/')
:output as string, replace \r\n to '\n'
>>> dev.start_activity('com.example.demo', '.Client')
None
>>> dev.stat('/data/local/tmp/_screen.png')
:posix.stat_result object
>>> dev.current_app()
com.example.demo
>>> dev.orientation()
: one of [1-4]
>>> dev.screenshot()
: PIL image object
>>> dev.keyevent('HOME')
None
>>> dev.open_minicap()
True
>>> dev.open_minitouch()
True
>>> dev.touch(100, 100)
None
>>> dev.swipe() # TODO
>>> dev.pinch() # only in minitouch
"""

import os
import re
import socket
import subprocess32 as subprocess


LOCAL_PORT = 10300
_init_local_port = LOCAL_PORT - 1

def next_local_port(adb_host=None):
    """ find avaliable free port """
    def is_port_listening(port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = s.connect_ex((str(adb_host) if adb_host else '127.0.0.1', port))
        s.close()
        return result == 0
    global _init_local_port
    _init_local_port = _init_local_port + 1 if _init_local_port < 32764 else LOCAL_PORT
    while is_port_listening(_init_local_port):
        _init_local_port += 1
    return _init_local_port


class Adb(object):
    __adb_cmd = None

    def __init__(self, serial=None, server_host=None, server_port=None):
        """
        Args:
            - serial: device serial number
            - server_host: adb server host, default 127.0.0.1
            - server_port: adb server port, default 5037
        """
        self.default_serial = serial if serial else os.environ.get("ANDROID_SERIAL", None)
        self.server_host = str(server_host if server_host else '127.0.0.1')
        self.server_port = str(server_port if server_port else '5037')
        self.adb_host_port_options = []
        if self.server_host not in ['localhost', '127.0.0.1']:
            self.adb_host_port_options += ["-H", self.server_host]
        if self.server_port != '5037':
            self.adb_host_port_options += ["-P", self.server_port]
        self.serial = serial or self.device_serial()

    @classmethod
    def adb(cls):
        """return adb binary full path"""
        if cls.__adb_cmd is None:
            if "ANDROID_HOME" in os.environ:
                filename = "adb.exe" if os.name == 'nt' else "adb"
                adb_cmd = os.path.join(os.environ["ANDROID_HOME"], "platform-tools", filename)
                if not os.path.exists(adb_cmd):
                    raise EnvironmentError(
                        "Adb not found in $ANDROID_HOME path: %s." % os.environ["ANDROID_HOME"])
            else:
                import distutils
                if "spawn" not in dir(distutils):
                    import distutils.spawn
                adb_cmd = distutils.spawn.find_executable("adb")
                if adb_cmd:
                    adb_cmd = os.path.realpath(adb_cmd)
                else:
                    raise EnvironmentError("$ANDROID_HOME environment not set.")
            cls.__adb_cmd = adb_cmd
        return cls.__adb_cmd

    def devices(self):
        '''get a dict of attached devices. key is the device serial, value is device name.'''
        out = self.raw_cmd('devices').communicate()[0].decode("utf-8")
        match = "List of devices attached"
        index = out.find(match)
        if index < 0:
            raise EnvironmentError("adb is not working.")
        return dict([s.split("\t") for s in out[index + len(match):].strip().splitlines() 
                if s.strip() and not s.strip().startswith('*')])

    def cmd(self, *args, **kwargs):
        '''adb command, add -s serial by default. return the subprocess.Popen object.'''
        serial = self.device_serial() # TODO(ssx): useless here, need to remove and test
        if serial:
            if " " in serial:  # TODO how to include special chars on command line
                serial = "'%s'" % serial
            return self.raw_cmd(*["-s", serial] + list(args))
        else:
            return self.raw_cmd(*args)

    def raw_cmd(self, *args):
        '''adb command. return the subprocess.Popen object.'''
        cmd_line = [self.adb()] + self.adb_host_port_options + list(args)
        if os.name != "nt":
            cmd_line = [" ".join(cmd_line)]
        return subprocess.Popen(cmd_line, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def build_cmd(self, *args):
        '''adb command array
        For example:
            build_cmd("shell", "uptime") will get
            ["adb", "-s", "xx..", "-P", "5037", "shell", "uptime"]
        '''
        return [self.adb(), "-s", self.serial] + self.adb_host_port_options + list(args)

    def device_serial(self):
        devices = self.devices()
        if not self.default_serial:
            if devices:
                if len(devices) is 1:
                    self.default_serial = list(devices.keys())[0]
                else:
                    raise EnvironmentError("Multiple devices attached but default android serial not set.")
            else:
                raise EnvironmentError("Device not attached.")
        else:
            if self.default_serial not in devices:
                raise EnvironmentError("Device(%s) not attached." % self.default_serial)

        if devices[self.default_serial] != 'device':
            raise EnvironmentError("Device(%s) is not ready. status(%s)." % 
                (self.default_serial, devices[self.default_serial]))
        return self.default_serial

    def forward(self, device_port, local_port=None):
        '''adb port forward. return local_port'''
        if local_port is None:
            for s, lp, rp in self.forward_list():
                if s == self.device_serial() and rp == 'tcp:%d' % device_port:
                    return int(lp[4:])
            return self.forward(device_port, next_local_port(self.server_host))
        else:
            self.cmd("forward", "tcp:%d" % local_port, "tcp:%d" % device_port).wait()
            return local_port

    def forward_list(self):
        '''adb forward --list'''
        version = self.version()
        if int(version[1]) <= 1 and int(version[2]) <= 0 and int(version[3]) < 31:
            raise EnvironmentError("Low adb version.")
        lines = self.raw_cmd("forward", "--list").communicate()[0].decode("utf-8").strip().splitlines()
        return [line.strip().split() for line in lines]

    def version(self):
        '''adb version'''
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", self.raw_cmd("version").communicate()[0].decode("utf-8"))
        return [match.group(i) for i in range(4)]

    def remove(self, path):
        """Remove remote file
        Return:
            bool: true or false"""
        p = self.cmd('shell', 'rm', path)
        stdout, stderr = p.communicate()
        if stdout or stderr:
            return False
        else:
            return True


if __name__ == '__main__':
    adb = Adb()
    print adb.version()
    print adb.devices()
    print adb.forward_list()
    print adb.forward(8001)