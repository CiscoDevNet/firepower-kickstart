from unicon.eal.dialogs import Dialog

class AsaDialog:
    ssh_console_dialog = Dialog([
        ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
        ['[P|p]assword:', 'sendline_ctx(password)', None, True, False],
        ['Last login:', None, None, False, False],
    ])

    ssh_vty_dialog = Dialog([
        ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
        ['[P|p]assword:', 'sendline_ctx(password)', None, True, False],
        ['for a list of available commands.', None, None, False, False],
    ])

    download_dialog = Dialog([
        ['Address or name of remote host \[.*\]', 'sendline()', None, True, False],
        ['Source username \[.*\]', 'sendline()', None, True, False],
        ['Source filename \[.*\]', 'sendline()', None, True, False],
        ['Destination filename \[.*\]', 'sendline()', None, True, False],
        ['Do you want to over write\?', 'sendline_ctx(overwrite)', None, True, False],
        ['[.*>#] ', 'sendline()', None, False, False],
    ])
