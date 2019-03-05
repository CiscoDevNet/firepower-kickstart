from unicon.eal.dialogs import Statement


class AsaStatements:
    def __init__(self, patterns):
        self.disable_to_enable_statement = Statement(
        	pattern=patterns.prompt.password_prompt,
            action=lambda spawn, password: spawn.sendline(password),
            args={'password': patterns.enable_password},
            loop_continue=True, continue_timer=True
          )

        self.set_enable_pwd_statement = Statement(
        	pattern=patterns.prompt.set_enable_pwd_prompt,
        	action=lambda spawn, password: spawn.sendline(password),
        	args={'password': patterns.enable_password},
        	loop_continue=True, continue_timer=True
        )

        self.repeat_enable_pwd_statement = Statement(
        	pattern=patterns.prompt.repeat_enable_pwd_prompt,
        	action=lambda spawn, password: spawn.sendline(password),
        	args={'password': patterns.enable_password},
        	loop_continue=True, continue_timer=True
        )
