from unicon.eal.dialogs import Statement


class M3Statements:
    def login_handler(spawn):
        spawn.sendline(self.patterns.login_username)
        spawn.expect('Password: ')
        spawn.sendline(self.patterns.login_password)
        spawn.expect('Cisco Firepower')
        spawn.sendline()

    def password_handler(spawn, password):
        spawn.sendline(password)

    def __init__(self, patterns):
        self.patterns = patterns
        self.login_password = Statement(pattern=self.patterns.prompt.prelogin_prompt,
                                        action=self.login_handler,
                                        args=None,
                                        loop_continue=True,
                                        continue_timer=True)

        self.login_password_statement = Statement(pattern=patterns.prompt.password_prompt,
                                                  action=self.password_handler,
                                                  args={'password': patterns.login_password},
                                                  loop_continue=True,
                                                  continue_timer=True)

        self.login_incorrect = Statement(pattern='Login incorrect',
                                         action=None,
                                         args=None,
                                         loop_continue=False,
                                         continue_timer=False)
