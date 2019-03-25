"""patterns.py.

Chassis statements

"""

from unicon.eal.dialogs import Statement


def login_handler(spawn, username, password):
    spawn.sendline(username)
    spawn.expect('Password: ')
    spawn.sendline(password)
    spawn.expect('Cisco Firepower')
    spawn.sendline()


class ChassisStatements:
    def __init__(self, patterns, chassis_data):
        username = \
            chassis_data['custom']['chassis_login']['username']
        password = \
            chassis_data['custom']['chassis_login']['password']
        self.login_password = \
            Statement(
                pattern=patterns.prompt.prelogin_prompt,
                action=login_handler,
                args={
                    'username': username,
                    'password': password
                },
                loop_continue=True, continue_timer=True)
