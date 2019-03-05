from unicon.eal.dialogs import Statement
from .patterns import Patterns

def password_handler(spawn, password):
    spawn.sendline(password)
    

class VmStatements(object):
    from .constants import VmConstants
    login_password_statement = Statement(pattern=Patterns.password_prompt,
                                         action = password_handler,
                                         args={'password': VmConstants.login_password},
                                         loop_continue=True,
                                         continue_timer=True)

    sudo_password_statement = Statement(pattern=Patterns.password_prompt,
                                        action = password_handler,
                                        args={'password': VmConstants.sudo_password},
                                        loop_continue=True,
                                        continue_timer=True)    

