from unicon.eal.dialogs import Dialog


class Ftd5500xDialog:
    def __init__(self, patterns):
        """Initializer of Ftd5500xDialogs."""
        self.patterns = patterns
        self.ssh_connect_dialog = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['Password:', 'sendline_ctx(password)', None, True, False],
            ['Password OK', 'sendline()', None, False, False],
            ['Last login:', None, None, True, False],
            # ['(.*Cisco.)*', None, None, False, False],
        ])

        # from disable to enable
        self.disable_to_enable = Dialog([[self.patterns.prompt.password_prompt,
                                         'sendline()', None, True, True]])
