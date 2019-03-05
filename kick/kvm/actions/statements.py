from unicon.eal.dialogs import Statement
from .patterns import Patterns

def password_handler(spawn, password):
    spawn.sendline(password)
    

class KvmStatements(object):
    from .constants import KvmConstants
    login_password_statement = Statement(pattern=Patterns.password_prompt,
                                         action = password_handler,
                                         args={'password': KvmConstants.kvm_login_password},
                                         loop_continue=True,
                                         continue_timer=True)

    sudo_password_statement = Statement(pattern=Patterns.password_prompt,
                                        action = password_handler,
                                        args={'password': KvmConstants.kvm_sudo_password},
                                        loop_continue=True,
                                        continue_timer=True)
                                        
