"""dialogs.py.

SSP dialogs for state transitions

"""
import time
from unicon.eal.dialogs import Dialog


def action_mio_to_fpr_module(spawn):
    time.sleep(0.5)
    spawn.sendline()
    spawn.sendline()


def ctrl_a_sleep_ctrl_d(spawn):
    spawn.send('\x01')
    time.sleep(0.5)
    spawn.send('\x04')
    time.sleep(0.5)
    spawn.send('\x01')
    time.sleep(0.5)
    spawn.send('d')
    time.sleep(0.5)


class SspDialogs:
    """An SSP class that restores all dialogs for state trasitions."""

    def __init__(self, patterns, deploy_type='native'):
        """Initializer of SspDialogs."""

        self.patterns = patterns

        # From login to MIO
        self.d_prelogin_to_mio = Dialog([[self.patterns.prompt.password_prompt,
                                          'sendline({})'.format(
                                              self.patterns.login_password),
                                          None, True, True], ])

        # from MIO to module boot cli
        self.d_mio_to_fpr_module = Dialog([
            ['Close Network Connection to Exit', action_mio_to_fpr_module, None,
             True, True],
            [self.patterns.prompt.fireos_prompt, "sendline(exit)", None, True,
             True],
            [self.patterns.prompt.expert_cli, "sendline(exit)", None, True,
             True],
            [self.patterns.prompt.sudo_prompt, "sendline(exit)", None, True,
             True],
            [r'\x07', "sendline({})".format(chr(3)), None, True, True], ])

        # from module boot cli to FTD
        self.d_fpr_module_to_ftd = Dialog([
            ['Connecting to.*ftd.*console', None, None, True, True],
            [r'\r\nEnter new password:',
             'sendline({})'.format(self.patterns.sudo_password), None, True,
             True],
            [r'\r\nConfirm new password:',
             'sendline({})'.format(self.patterns.sudo_password), None, True,
             True],
            ['to return to bootCLI', "sendline()", None, True, True],
            ['configure manager add DONTRESOLVE', "sendline()", None, True,
             True]], )

        self.d_fireos_to_fpr = Dialog([
            ['Disconnected.*>d', "sendline(\x08)", None, True, True]
        ])

        # ?
        self.d_fpr_to_fpr = Dialog([
            ['ftd not installed', 'sendline({})'.format(chr(3)), None, True,
             True]])

        # from FTD expert to sudo mode
        self.d_expert_to_sudo = Dialog([
            [self.patterns.prompt.password_prompt,
             'sendline({})'.format(self.patterns.sudo_password), None, True,
             True]])

        # from module boot cli to MIO
        self.d_fpr_module_to_mio = Dialog(
            [
                ['telnet>', 'sendline("q")', None, True, True],
                ['No such command.+exit', 'sendline(~)', None, True, True],
                ['No such command.+~', 'sendline(exit)', None, True, True],
            ])

        # from disable to enable
        self.disable_to_enable = Dialog([[self.patterns.prompt.password_prompt,
                                          'sendline()', None, True, True]])

        # from disable to fireos
        self.d_disable_to_fireos = Dialog([
            [self.patterns.prompt.expert_cli, 'sendline(exit)', None, True,
             True],
        ])

        # from disable to expert
        self.d_disable_to_expert = Dialog([
            [self.patterns.prompt.fireos_prompt, 'sendline(expert)', None, True,
             True],
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
            ['Request refused. Exiting ...', None, None, False, False],
            [self.patterns.prompt.enable_prompt, 'sendline(conf t)', None, True,
             True],
        ])
