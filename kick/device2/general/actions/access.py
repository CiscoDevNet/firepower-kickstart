"""Methods to check whether device is available via its console."""

import logging
import time

try:
    from kick.misc.convert_bytes import string_to_bytes
except ImportError:
    from kick.miscellaneous.convert import string_to_bytes

from unicon.eal.dialogs import Dialog
from kick.miscellaneous.credentials import *
from unicon.eal.expect import Spawn, TimeoutError

LOGGER = logging.getLogger(__name__)
HANDLER = logging.StreamHandler()
FORMATTER = logging.Formatter('%(asctime)s : %(levelname)s : %(name)s : %(message)s')
HANDLER.setFormatter(FORMATTER)
LOGGER.addHandler(HANDLER)

DEFAULT_TIMEOUT = 60
DEFAULT_USERNAME = 'myusername'
DEFAULT_PASSWORD = 'mypassword'
DEFAULT_ENPASSWORD = 'myenpassword'

VALID_PROMPTS = ['ciscoasa>', '\r\nciscoasa:~\$', '.*login:', 'rommon.*>', '.*-boot>', '\r\n[\x07]?>', '.*# $',
                 '\r\n.*@.*\$ $']

def wait_until_available(host, port, timeout=300, user=DEFAULT_USERNAME,
                         pwd=DEFAULT_PASSWORD, prompt='login:', access='telnet'):
    """Wait until device is available up to the timeout. If not, raise an
    exception.

    :param host: Ip of the device/console
    :param port: console port
    :param timeout: timeout
    :param user: username
    :param pwd: password
    :param prompt: expected prompt
    :param access: type of access: telnet or ssh
    :return: True if device is available, False if it's not

    """

    LOGGER.info('Wait until %s on port %s is available; timeout=%d'
                % (host, port, timeout))

    if user == DEFAULT_USERNAME:
        user = get_username(user)
    if pwd == DEFAULT_PASSWORD:
        pwd = get_password(pwd)

    first_time = True
    start_time = time.time()
    while first_time or (start_time + timeout > time.time()):
        if is_available(host, port, user, pwd, prompt, access):
            LOGGER.info('%s on port %s is available in %d seconds' %
                        (host, port, round(time.time() - start_time, 1)))
            return True
        else:
            time.sleep(5)
            first_time = False
    LOGGER.error('Cannot connect to %s on port %d in %d seconds' %
                 (host, port, timeout))


def is_available(host, port, user=DEFAULT_USERNAME, pwd=DEFAULT_PASSWORD,
                 prompt='firepower login:', access='telnet'):
    """Checks whether device is available.

    :param host: Ip of the device/console
    :param port: console port
    :param user: username
    :param pwd: password
    :param prompt: expected prompt
    :param access: type of access: telnet or ssh
    :return: True if device is available, False if it's not

    """

    if user == DEFAULT_USERNAME:
        user = get_username(user)
    if pwd == DEFAULT_PASSWORD:
        pwd = get_password(pwd)

    VALID_PROMPTS.append(prompt)
    if access == 'telnet':
        spawn_id = Spawn('telnet {} {}\n'.format(host, port))
        try:
            spawn_id.expect(
                "Connected to.*Escape character is '\^\]'\..*Username: ")
        except OSError:
            if port is not 23:
                clear_line(host=host, port=int(port) % 100, user=user, pwd=pwd, en_password=pwd)
            spawn_id = Spawn('telnet {} {}\n'.format(host, port))
            try:
                spawn_id.expect("Connected to.*Escape character is '\^\]'\..*Username: ")
            except OSError:
                spawn_id.close()
                return False
        spawn_id.sendline(user)
        spawn_id.expect("Password: ")
        spawn_id.sendline(pwd)
        try:
            spawn_id.expect("Password OK.*")
        except TimeoutError:
            LOGGER.debug("'Password OK' message did not appear ... continue")
        spawn_id.sendline('')
        try:
            __wait_for_rommon(spawn_id, 900)
        except:
            LOGGER.info("\nFailed to get a valid prompt")
            spawn_id.close()
            return False
        LOGGER.info('%s on port %d is available' % (host, port))
        spawn_id.close()
    elif access == 'ssh':
        try:
            if port is not 22:
                clear_line(host=host, port=port % 100, access='ssh', user=user, pwd=pwd, en_password=pwd)
            spawn_id = Spawn('ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -l {} -p {} {}'.
                             format(user, port, host))
            d1 = Dialog([
                ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
                ['(P|p)assword:', 'sendline({})'.format(pwd), None, False, False],
                ['Connection refused', None, None, False, False],
            ])
            d1.process(spawn_id, timeout=60)
            try:
                spawn_id.expect("Password OK.*")
            except:
                pass
            spawn_id.sendline()
            time.sleep(10)
            try:
                __wait_for_rommon(spawn_id, 900)
            except:
                LOGGER.info("\nFailed to get a valid prompt")
                spawn_id.close()
                return False
            LOGGER.info('%s on port %d is available' % (host, port))
            spawn_id.close()
        except:
            return False
    else:
        raise RuntimeError('Device can be accessed only by telnet or ssh')

    return True


def __wait_for_rommon(spawn_id, timeout):
    # The system will reboot, wait for the following prompts
    d = Dialog([['Use BREAK or ESC to interrupt boot', 'sendline({})'.format(chr(27)), None, True, False],
                ])
    
    for prompt in VALID_PROMPTS:
        d.append([prompt, None, None, False, False], )

    d.process(spawn_id, timeout=timeout)


def tty_id_from_roty_id(spawn, port):
    """
        Function that determines the tty identifier from the roty port
        :param spawn: the spawn connection
        :param port: the roty port
        :return: the tty identifier for the line
    """
    spawn.sendline('show line\n')
    time.sleep(3)
    output_lines = []
    # parse show line output into lines list
    while True:
        match_output = spawn.expect('.*').match_output
        output_lines.extend(match_output.split('\n'))
        if '--More--' in match_output:
            spawn.sendline('\x20')
            time.sleep(3)
        else:
            break

    # determine header column indexes
    header = None
    header_roty_index = None
    header_tty_index = None
    for i in range(len(output_lines)):
        # only determine the header once, the first
        # encountered header
        output_lines[i] = output_lines[i].replace('--More--', '')
        output_lines[i] = output_lines[i].replace('\b', '')
        output_lines[i] = output_lines[i].strip()
        if not header:
            if 'Tty' in output_lines[i]:
                header = tuple(output_lines[i].split())
                for j in range(len(header)):
                    if header[j] == 'Roty':
                        header_roty_index = j
                    if header[j] == 'Tty':
                        header_tty_index = j
        if len(output_lines[i]) > 0:
            if output_lines[i][0] == '*':
                # when the line starts with * and the *
                # is not separated by a space from the following
                # column we need to separate it manually
                # for consistency
                if output_lines[i][1] != ' ':
                    output_lines[i] = output_lines[i][0] + ' ' + output_lines[i][1:]
            else:
                # and make uniform the rest of the lines also with a dummy character
                # instead of *
                output_lines[i] = '@ ' + output_lines[i][:]

    # if the header is not present we can't reliably
    # determine the fields
    if not header:
        raise RuntimeError('no Tty column found in show line header.')

    # if the roty and tty fields are not displayed
    # we can't realiably determine the line
    if header_roty_index is None or header_tty_index is None:
        raise RuntimeError('show line is not showing the Tty and Roty columns.')

    # offsetting the columns accordingly to account
    # for * and @ at the start of the lines
    header_roty_index += 1
    header_tty_index += 1

    # determine tty line id from roty id
    line_id = None
    for line in output_lines:
        fields = tuple(line.split())
        try:
            if int(fields[header_roty_index]) == port:
                line_id = fields[header_tty_index]
                break
        except:
            # if we cannot convert the roty id to an int
            # we consider that things are not correctly configured
            # and go to the next output line and continue searching
            pass
    return line_id


def clear_line(host, port, user=DEFAULT_USERNAME, pwd=DEFAULT_PASSWORD, prompt='#',
               access='telnet', en_password=DEFAULT_ENPASSWORD, timeout=None):
    """Clear line corresponding to a device; this is required because only a
    single console connection is available.

    If somebody or some process failed to close the connection, it
    should be cleared explicitly.
    
    This function accepts only ssh and telnet connections.

    :param host: ip address of terminal server
    :param port: device line number in terminal server to be cleared
                for example, if port 2005 is mapped to line 5, port=5
    :param user: username
    :param pwd: password
    :param prompt: expected prompt after logging in
    :param access: ssh or telnet; default is set to telnet
    :param en_password: enable password to switch to line configuration mode
    :param timeout: how long the connection and authentication would take in seconds;
                    if not provided, default is 60s
    :return: None
    
    """

    if user == DEFAULT_USERNAME:
        user = get_username(user)
    if pwd == DEFAULT_PASSWORD:
        pwd = get_password(pwd)
    if en_password == DEFAULT_ENPASSWORD:
        en_password = get_password(en_password)

    if not timeout:
        timeout = DEFAULT_TIMEOUT

    d1 = None
    spawn = None

    # establish a connection to the terminal server
    if access == 'telnet':
        spawn = Spawn('telnet {} {}'.format(host, '23'))
        d1 = Dialog([
            ["Connected to.*Escape character is '\^\]'\.", 'sendline()', None, True, False],
            ['.*Username:', 'sendline({})'.format(user), None, True, False],
            ['(p|P)assword:', 'sendline({})'.format(pwd), None, True, True],
            [prompt, 'sendline()', None, False, False],
            ['>', 'sendline()', None, False, False],
        ])

    elif access == 'ssh':
        spawn = Spawn('ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no '
                      '-l {} -p {} {}'.format(user, '22', host))
        d1 = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['(p|P)assword:', 'sendline({})'.format(pwd), None, False, False],
        ])

    else:
        LOGGER.error('Unknown protocol: Telnet or ssh supported only')

    try:
        LOGGER.info('Trying to connect to {}'.format(host))
        d1.process(spawn, timeout=timeout)
        try:
            spawn.expect("Password OK.*")
        except TimeoutError:
            LOGGER.info("'Password OK' message didn't appear")
            pass
        spawn.sendline()
    except TimeoutError:
        LOGGER.error('Failed to connect to terminal server')
        raise Exception('Failed to connect to terminal server')

    # clear port section
    try:
        spawn.expect('#')
    except:
        # expect >
        spawn.sendline('en')
        try:
            spawn.expect('Password:')
            spawn.sendline(en_password)
        except:
            pass
    try:
        line_id = tty_id_from_roty_id(spawn, port)
        LOGGER.info('detected line number for clearing: {} from port {}'.
                    format(line_id, port))
        if line_id:
            spawn.sendline('clear line {}'.format(line_id))
            spawn.expect('[confirm]')
            spawn.sendline('')
            spawn.expect('[OK]')
            LOGGER.info('line: {} was cleared'.format(port))
        spawn.close()
    except TimeoutError:
        spawn.close()
        LOGGER.error('Line: {} was not cleared'.format(port))
        raise Exception('Line {} was NOT cleared'.format(port))
