from unicon.eal.dialogs import Statement
import logging
import time
logger = logging.getLogger(__name__)


def login_handler(spawn, patterns):
    spawn.sendline(patterns.login_username)
    spawn.expect('Password: ')
    spawn.sendline(patterns.login_password)
    r = spawn.expect(['Cisco Firepower', 'Login incorrect'], timeout=10)
    if 'Login incorrect' in r.match_output:
        login_with_factory_default_password(spawn, patterns)

    # if no sleep after login, device will enter a weird state when "connect ftd"
    # is sent, it echoes back "> connect ftd", instead of "> ". What's worse is
    # from here, you can't type anything in. you have to ctrl+u to clear the
    # existing string ("connect ftd") before anything. a sleep will avoid it.
    time.sleep(3)
    spawn.sendline()


def login_with_factory_default_password(spawn, patterns):
    # see CSCvq65263 for details: if device went through an incomplete baseline, it may
    # contain the factory default password "Admin123", which is worth a try for baseline
    # to continue. It's the user's responsibility to not do anything else other than
    # a new baseline.
    logger.debug("Trying factory default password (Admin123)")
    spawn.sendline(patterns.login_username)
    spawn.expect('Password: ')
    spawn.sendline('Admin123')
    spawn.expect('Cisco Firepower')
    logger.debug("factory default password works!")
    logger.debug("Device uses unexpected password of factory default.")
    logger.warning("You need to baseline the device right away.")
    spawn.sendline()


class KpStatements:
    def __init__(self, patterns):
        self.login_password = Statement(pattern=patterns.prompt.prelogin_prompt,
                                        action=login_handler,
                                        args={'patterns': patterns},
                                        loop_continue=False,
                                        continue_timer=True)

        self.login_incorrect = Statement(pattern='Login incorrect',
                                         action=login_with_factory_default_password,
                                         args={'patterns': patterns},
                                         loop_continue=False,
                                         continue_timer=False)
