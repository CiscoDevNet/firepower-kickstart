"""Perform power-bar options on a device."""
import logging
import re
import telnetlib
import time

try:
    from kick.misc.convert_bytes import string_to_bytes, bytes_to_string
except ImportError:
    from kick.miscellaneous.convert import string_to_bytes, bytes_to_string

LOGGER = logging.getLogger(__name__)
HANDLER = logging.StreamHandler()
FORMATTER = logging.Formatter('%(asctime)s : %(levelname)s : %(name)s : %(message)s')
HANDLER.setFormatter(FORMATTER)
LOGGER.addHandler(HANDLER)


def power_bar(
              power_server,
              port,
              action='status',
              user='admn',
              pwd='admn'):
    """Telnet to power-bar and perform the specified action

    :param power_server: name or IP Address of power-bar
    :param port: port of the device to perform power action
    :param action: status, on, off, or reboot
    :param user: power-bar credential
    :param pwd: power-bar credential
    :return:
 
    """

    actions = ['status', 'on', 'off', 'reboot']
    LOGGER.info('power_bar %s port=%s action=%s' % (power_server, port, action))
    if not action.lower() in actions:
        raise ValueError('action should be one of %s' % str(actions))

    # defined common patterns for the different versions of PDU
    pattern = r'.*\.?%s +[^ ]+ +([^ ]+).*' % port if action.lower() == 'status' \
        else r'.*(Command successful).*'

    try:
        # match both 'Switched PDU:' and 'Switched CDU:' menu selection
        prompt = [string_to_bytes("Switched .*:")]
        session = telnetlib.Telnet(power_server)
        session.read_until(string_to_bytes("Username:"))
        session.write(string_to_bytes(user + '\n'))
        session.read_until(string_to_bytes("Password:"))
        session.write(string_to_bytes(pwd + '\n'))
        session.expect(prompt)
        session.write(string_to_bytes('%s .%s\n' % (action, port)))
        # expect returns a tuple, where the last element is
        # the text read up till and including the match
        result = session.expect(prompt)[2]
        for line in result.splitlines():
            LOGGER.debug(line)
        return re.search(pattern, bytes_to_string(result), re.IGNORECASE).group(1)
    finally:
        try:
            session.close()
        except:
            pass


def power_cycle_all_ports(power_bar_server, power_bar_port, power_bar_user, power_bar_pwd):
    """Powers off and then powers on all given ports.

    :param power_bar_server: comma-separated string of IP addresses of the PDU's
    :param power_bar_port: comma-separated string of power port on the PDU's
    :param power_bar_user: comma-separated usernames for power bar servers
    :param power_bar_pwd:  comma-separated passwords for power bar servers
    :return: True if all ports were powered off and on successfully, False otherwise
    """

    result = True
    power_bar_servers = [server.strip() for server in power_bar_server.split(',')]
    power_bar_ports = [port.strip() for port in power_bar_port.split(',')]
    power_bar_users = [user.strip() for user in power_bar_user.split(',')]
    power_bar_pwds = [pwd.strip() for pwd in power_bar_pwd.split(',')]
    LOGGER.info('->Power off all power ports')
    for server, port, user, pwd in zip(power_bar_servers, power_bar_ports, power_bar_users, power_bar_pwds):
        LOGGER.info('->Power off {} {}'.format(server, port))
        result = result and power_bar(server, port, action='off', user=user, pwd=pwd)
        LOGGER.info('->Done ')
        time.sleep(10)
    LOGGER.info("Sleeping for 60 secs..")
    time.sleep(60)
    LOGGER.info('->Power on all power ports')
    for server, port, user, pwd in zip(power_bar_servers, power_bar_ports, power_bar_users, power_bar_pwds):
        LOGGER.info('->Power on {} {}'.format(server, port))
        result = result and power_bar(server, port, action='on', user=user, pwd=pwd)
        LOGGER.info('->Done')
        time.sleep(10)

    return result
