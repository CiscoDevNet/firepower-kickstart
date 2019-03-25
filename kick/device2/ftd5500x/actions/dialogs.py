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

        # from disable to fireos
        self.d_disable_to_fireos = Dialog([
            [self.patterns.prompt.expert_prompt, 'sendline(exit)', None, True,
             True],
        ])

        # from expert to disable
        self.d_expert_to_disable = Dialog([
            [self.patterns.prompt.enable_prompt, 'sendline(disable)', None,
             True, True],
            ['Request refused. Exiting ...', None, None, False, False],
            [self.patterns.prompt.password_prompt, 'sendline({})'.format(self.patterns.sudo_password),
             None, True, True]
        ])

        # from enable to disable
        self.d_enable_to_disable = Dialog([
            [self.patterns.prompt.enable_prompt, 'sendline(disable)', None,
             True, True],
            ['Request refused. Exiting ...', None, None, False, False],
            [self.patterns.prompt.config_prompt, 'sendline(end)', None, True,
             True]
        ])

        # from disable to enable
        self.d_disable_to_enable = Dialog([
            [self.patterns.prompt.disable_prompt, 'sendline(en)', None, True,
             True],
            [self.patterns.prompt.password_prompt, 'sendline()', None, True,
             True],
            ['Request refused. Exiting ...', None, None, False, False],
            [self.patterns.prompt.config_prompt, 'sendline(end)', None, True,
             True],
        ])

        # from enable/disable to conft
        self.d_endisable_to_conft = Dialog([
            [self.patterns.prompt.disable_prompt, 'sendline(en)', None, True,
             True],
            [self.patterns.prompt.password_prompt, 'sendline()', None, True,
             True],
            [self.patterns.prompt.enable_prompt, 'sendline(conf t)', None, True,
             True],
        ])
