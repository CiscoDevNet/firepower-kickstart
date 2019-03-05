from unicon.eal.dialogs import Dialog

class KvmDialog:

    ssh_connect_dialog = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['Password: ', 'sendline({})'.format(password),
             None, True, False],
            ['Last login:', None, None, False, False],
    ])