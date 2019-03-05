from unicon.eal.dialogs import Statement


def password_handler(spawn, password):
    spawn.sendline(password)


class EpStatements:
    def login_handler(spawn):
        spawn.sendline(self.patterns.login_username)
        spawn.expect('Password: ')
        spawn.sendline(self.patterns.login_password)
        spawn.expect('Cisco Firepower')
        spawn.sendline()

    def __init__(self, patterns):
        self.patterns = patterns
        self.login_password = Statement(pattern=self.patterns.prompt.prelogin_prompt,
                                        action=self.login_handler,
                                        args=None,
                                        loop_continue=True,
                                        continue_timer=True)

        self.login_password_statement = Statement(pattern=patterns.prompt.password_prompt,
                                                  action=password_handler,
                                                  args={'password': patterns.login_password},
                                                  loop_continue=True,
                                                  continue_timer=True)
