from unicon.eal.dialogs import Dialog


class Series3Dialog:
    def __init__(self, patterns):
        self.patterns = patterns
        self.ssh_connect_dialog = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            #['Password:', 'sendline_ctx({})'.format(self.patterns.login_password), None, True, False],
            ['Password:', 'sendline_ctx(password)', None, True, False],
            ['Password OK', 'sendline()', None, False, False],
            ['Last login:', None, None, True, False],
            # ['(.*Cisco.)*', None, None, False, False],
        ])
