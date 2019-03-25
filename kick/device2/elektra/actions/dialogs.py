from unicon.eal.dialogs import Dialog


class ElektraDialog:
    def __init__(self, patterns):
        """Initializer of ElektraDialogs."""

        self.patterns = patterns
        self.ssh_connect_dialog = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['Password:', 'sendline_ctx(password)', None, True, False],
            ['Password OK', 'sendline()', None, False, False],
            ['Last login:', None, None, True, False],
            # ['(.*Cisco.)*', None, None, False, False],
        ])

        self.sfr_dialog = Dialog([
            ['Clear the current console connection', 'sendline()', None, True,
             True],
            [self.patterns.prompt.sudo_prompt, 'sendline(exit)', None, True,
             True],
            [self.patterns.prompt.fireos_prompt, 'sendline(expert)', None, True,
             True],
            [self.patterns.prompt.prelogin_prompt, 'sendline({})'.format(self.patterns.username), None, True,
             True],
            [self.patterns.prompt.password_prompt, 'sendline({})'.format(self.patterns.login_password), None, True,
             True],
        ])
