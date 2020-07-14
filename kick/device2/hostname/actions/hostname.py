"""
This script is to set the hostname as given in the testbed file to given WM/KP device
Connect to device console (ssh or telnet) as per the connection protocol defined in testbed.
check if FTD(app) is present, if present update the hostname from ftt app, if not change hostname from FXOS itself

"""


import pexpect
import sys
import time
import re
import os
from kick.device2.general.actions.access import clear_line
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
LEVEL = logging.DEBUG
console_handler = logging.StreamHandler()
kick_logger = logging.getLogger('kick')
kick_logger.setLevel(LEVEL)
kick_logger.addHandler(console_handler)


class ChangeHostname():

    def __init__(self):

        """Constructor of device for hostname change

        :return: None

        """
        pass


    def connect_to_ssh_console_line(self,ts_ip, port, username='vppuser', password='vppuser'):
        """
        get pexpect line.

        ts_ip: terminal server ip (or hostname)
        port: port on terminal server
        """
        clear_line(host=ts_ip, port=int(port) % 100, user=username, pwd=password, access='ssh')
        line = pexpect.spawn("ssh -l {} -p {} {}".format(username, port, ts_ip))
        log_prefix = os.path.splitext(os.path.basename(__file__))[0]
        line.logfile = open('{}.pexpect'.format(log_prefix), 'wb')
        try:
            line.expect("Are you sure you want to continue", timeout=3)
            line.sendline('yes')
        except:
            pass
        line.expect("Password: ")
        line.sendline(password)
        line.expect("Password OK")
        time.sleep(3)
        logger.debug("*******connected to ssh console********")
        return line

    def connect_to_telnet_console_line(self,ts_ip, port, username='vppuser', password='vppuser'):
        """
        get pexpect line.

        ts_ip: terminal server ip (or hostname)
        port: port on terminal server
        """
        clear_line(host=ts_ip, port=int(port) % 100, user=username, pwd=password, access='telnet')
        line = pexpect.spawn("telnet {} {}".format(ts_ip, port))
        log_prefix = os.path.splitext(os.path.basename(__file__))[0]
        line.logfile = open('{}.pexpect'.format(log_prefix), 'wb')

        try:
            line.expect("Connected to.*Escape character is '\^\]'\.", timeout=3)
            line.sendline('')
            logger.debug("*******connected to telnet console without credential********")
        except:
            line.expect("Connected to.*Escape character is '\^\]'\..*Username: ")
            line.sendline(username)
            line.expect("Password: ", timeout=3)
            line.sendline(password)
            line.sendline('')
            logger.debug("*******connected to telnet console with credential********")

        time.sleep(3)
        return line

    def disconnect_from_ssh_console_line(self,line):
        """
        Send disconnect sequence to line.
        """
        # send ctrl+u, \n + ~.
        line.sendcontrol("u")
        line.sendline()
        line.send('~.')
        try:
            line.expect('Connection to .* closed.')
            logger.debug('ssh line disconnected successfully')
        except OSError as e:
            logger.debug('Connection closed message did not appear: '
                            'Encountered exception: {}.'.format(
                traceback.format_tb(e.__traceback__)))
        line.logfile.close()
        logger.info("*******disconnected from ssh console********")

    def drop_to_prelogin(self, line, max_depth=10):
        """
        Drop line (from any other states) to prelogin, by repeatedly doing
        "exit".
        One added benefit of this step is, it forces the transition of
        sudo -> expert -> fireos state. So the future login will be more
        predictable.
        """
        for i in range(max_depth):
            # send ctrl + u, then exit
            # import pdb; pdb.set_trace()
            line.sendcontrol("u")
            time.sleep(1)
            line.sendline("exit")
            time.sleep(1)
            try:
                line.expect(["login: ", "Password: "], timeout=5) # password auth takes long. 5 seconds are needed.
                # logger.debug("DEBUG: after try{}".format(line.before.decode('utf-8')))
                time.sleep(1)
            except:
                pass
            else:
                logger.info("********in prelogin prompt********")
                time.sleep(3)
                break
        else:
            raise RuntimeError("Cannot get to prelogin after 10 exits.")

    def change_hostname_through_ftd(self,line, hostname, username="admin",
                                    password="Ci5c05n0rt!"):
        """
        Connect to ftd, go to sudo state, and change hostname there.
        """
        line.sendline("connect ftd")
        line.expect("> ")
        line.sendline("expert")
        line.expect("admin@.*:/.*\$ ")
        line.sendline("sudo su")
        line.expect("Password: ")
        line.sendline(password)
        line.expect("root@.*:/.*# ")
        line.sendline("hostname {}".format(hostname))
        line.expect("root@.*:/.*# ")
        line.sendline("exit")
        line.expect("admin@.*:/.*\$ ")
        line.sendline("exit")
        line.expect(">")
        line.sendline("exit")

    def change_hostname_through_scope_system(self,line, hostname):
        """
        Change hostname from scope system. This only works if no ftd app is present.
        """
        line.sendline("scope system\nset name {}\ncommit-buffer\nexit".format(hostname))

    def from_prelogin_to_logged_in(self,line, username, password):
        """
        Move from prelogin state to logged_in.
        """
        # import pdb; pdb.set_trace()
        line.sendcontrol("u")
        time.sleep(1)
        line.sendline()
        line.expect("login: ")
        line.sendline(username)
        line.expect("Password: ")
        line.sendline(password)
        line.expect("Last login: ")
        line.expect("[\r\n]+\S+# ")

    def from_logged_in_to_rommon(self,line):

        """
                Move from prelogin state to logged_in as this is the only way to recover device from "failed" state
        """
        line.sendline()
        line.sendline("connect local-mgmt")
        line.sendline("format everything")
        line.expect("Do you still want to format")
        line.sendline("yes")
        line.expect("Boot in 10 seconds.", timeout=180)
        line.send(chr(27))
        line.expect("[\r\n]+rommon.*> ")

    def change_hostname_from_prelogin(self,line, hostname, username="admin",
                                      password="Ci5c05n0rt!"):

        # go to chassis prompt
        self.from_prelogin_to_logged_in(line, username, password)

        # check if ftd is present
        line.sendline("top\nscope ssa\nshow app\ntop")
        try:
            line.expect("non-existing", timeout=5)
        except:
            pass
        with_ftd = self.check_if_ftd_is_present(line.before.decode('utf-8'))

        if with_ftd:
            line.sendline("connect ftd")
            # in case ftd is in sudo/expert state, force it to go through multiple
            # "exit" sequences, so that device ends up in fireos state.
            self.drop_to_prelogin(line)
            self.from_prelogin_to_logged_in(line, username, password)
            self.change_hostname_through_ftd(line, hostname, username, password)
        else:
            self.change_hostname_through_scope_system(line, hostname)

        line.expect("{}# ".format(hostname))

        logger.info("********hostname changed********")

    def check_if_ftd_is_present(self,show_app_output):
        """
        Check if there is an ftd app present.
        """
        r = re.search("ftd\s+[\d\.]+[^\r\n]+Application", show_app_output)
        if r:
            logger.info("*********ftd app found**********")
            return True
        else:
            logger.info("*********ftd app NOT found**********")
            return False


