from unicon.eal.dialogs import Dialog


class Elektra5585Dialog:
    def __init__(self, patterns):
        """Initializer of Elektra5585Dialogs."""
        self.patterns = patterns
        self.ssh_connect_dialog = Dialog([
            ['continue connecting (yes/no)?', 'sendline(yes)', None, True, False],
            ['Password:', 'sendline_ctx(password)', None, True, False],
            ['Password OK', 'sendline()', None, False, False],
            ['Last login:', None, None, True, False],
        ])
