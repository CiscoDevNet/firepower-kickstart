from unicon.eal.dialogs import Dialog


class M4Dialogs:
    # Dialogs for state transitions
    def __init__(self, patterns):
        self.patterns = patterns
        self.d_mio_to_admin = Dialog([['to Exit',
                                       'sendline()',
                                       None, True, True],
                                      [self.patterns.prompt.prelogin_prompt,
                                       'sendline({})'.format(self.patterns.login_username),
                                       None, True, True],
                                      [self.patterns.prompt.password_prompt,
                                       'sendline({})'.format(self.patterns.login_password),
                                       None, True, True],
                                      ])
        self.d_admin_to_sudo = Dialog([[self.patterns.prompt.password_prompt,
                                        'sendline({})'.format(self.patterns.sudo_password),
                                        None, True, True], ])
