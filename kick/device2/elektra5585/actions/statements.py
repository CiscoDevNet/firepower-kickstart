from unicon.eal.dialogs import Statement


def password_handler(spawn, password):
    spawn.sendline(password)


class Elektra5585Statements:
    def __init__(self, patterns):
        self.login_password_statement = Statement(pattern=patterns.prompt.password_prompt,
                                             action = password_handler,
                                             args={'password': patterns.login_password},
                                             loop_continue=True,
                                             continue_timer=True)

        self.pkg_password_statement = Statement(pattern=patterns.prompt.password_prompt,
                                             action = password_handler,
                                             args={'password': patterns.default_password},
                                             loop_continue=True,
                                             continue_timer=True)

        self.sudo_password_statement = Statement(pattern=patterns.prompt.password_prompt,
                                        action=password_handler,
                                        args={'password': patterns.sudo_password},
                                        loop_continue=True,
                                        continue_timer=True)
