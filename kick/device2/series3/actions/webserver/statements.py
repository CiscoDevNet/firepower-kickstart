from unicon.eal.dialogs import Statement
from .patterns import WebserverPatterns
from .constants import WebserverConstants


def password_handler(spawn, password):
    spawn.sendline(password)


class WebserverStatements:
    login_password_statement = Statement(pattern=WebserverPatterns.password_prompt,
                                         action = password_handler,
                                         args={'password': WebserverConstants.login_password},
                                         loop_continue=True,
                                         continue_timer=True)
    sudo_password_statement = Statement(pattern=WebserverPatterns.password_prompt,
                                        action = password_handler,
                                        args={'password': WebserverConstants.sudo_password},
                                        loop_continue=True,
                                        continue_timer=True)

