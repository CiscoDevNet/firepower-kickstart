from unicon.eal.dialogs import Dialog
from kick.device2.ftd5500x.actions.dialogs import Ftd5500xDialog


class KpDialogs:
    # Dialogs for state transitions
    def __init__(self, patterns):
        """Initializer of KpDialogs."""
        self.patterns = patterns
        self.d_expert_to_sudo = Dialog([[self.patterns.prompt.password_prompt,
                                         'sendline({})'.format(self.patterns.sudo_password),
                                         None, True, True], ])
        self.d_ftd_to_fxos = Dialog([
            ["Please enter 'exit' to go back", 'sendline(exit)', None, True, False], ])

        # KP forces user to re-define enable password. User should use the same
        # password as sudo_password
        self.disable_to_enable = Dialog([[self.patterns.prompt.password_prompt,
                                          'sendline({})'.format(self.patterns.sudo_password), None, True, True]])

        self.ftd_dialogs = Ftd5500xDialog(patterns)
