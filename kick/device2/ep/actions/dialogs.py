from unicon.eal.dialogs import Dialog


class EpDialogs:
    # Dialogs for state transitions
    def __init__(self, patterns):
        self.patterns = patterns
        self.d_admin_to_sudo = Dialog([[self.patterns.prompt.password_prompt,
                                        'sendline({})'.format(self.patterns.sudo_password),
                                        None, True, True], ])
