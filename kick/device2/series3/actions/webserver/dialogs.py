from unicon.eal.dialogs import Dialog
from .constants import WebserverConstants


class WebserverDialog:
    ssh_connect_dialog = Dialog([
        ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
        ['Password:', 'sendline_ctx(password)', None, True, False],
        ['Last login:', None , None, True, False],
    ])
