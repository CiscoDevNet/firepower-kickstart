from unicon.eal.dialogs import Dialog
from unicon.statemachine import State, Path, StateMachine

from .dialogs import FmcDialogs
from .statements import FmcStatements


class FmcStatemachine(StateMachine):
    def __init__(self, patterns):
        """ Constructor of state machine for FMC
        """
        self.patterns = patterns
        self.dialogs = FmcDialogs(self.patterns)
        self.statements = FmcStatements(self.patterns)
        super().__init__()

    def create(self):
        # Create States and their state patterns
        prelogin_state = State('prelogin_state', self.patterns.prompt.prelogin_prompt)
        admin_state = State('admin_state', self.patterns.prompt.admin_prompt)
        sudo_state = State('sudo_state', self.patterns.prompt.sudo_prompt)
        fireos_state = State('fireos_state', self.patterns.prompt.fireos_prompt)
        liloboot_state = State('liloboot_state', self.patterns.prompt.lilo_boot_prompt)
        liloos_state = State('lilos_state', self.patterns.prompt.lilo_os_prompt)
        lilo_boot_menu_state = State('lilobootmenu_state', self.patterns.prompt.lilo_boot_menu_prompt)

        # Add our states to the state machine
        self.add_state(admin_state)
        self.add_state(sudo_state)
        self.add_state(prelogin_state)
        self.add_state(fireos_state)
        self.add_state(liloboot_state)
        self.add_state(liloos_state)
        self.add_state(lilo_boot_menu_state)

        # Create paths for switching between states
        admin_to_sudo = Path(admin_state, sudo_state, 'sudo su -',
                             self.dialogs.d_admin_to_sudo)

        sudo_to_admin = Path(sudo_state, admin_state, "exit", None)

        prelogin_to_admin = Path(prelogin_state, admin_state, 'admin',
                                 Dialog([self.statements.login_password_statement]))

        admin_to_prelogin = Path(admin_state, prelogin_state, 'exit', None)

        # transitions from and to 'fireos_state' state
        fireos_to_admin_path = Path(fireos_state, admin_state, 'expert', None)
        admin_to_fireos_path = Path(admin_state, fireos_state, 'exit', None)
        fireos_to_prelogin = Path(fireos_state, prelogin_state, 'exit', None)

        # Add paths to the State Machine
        self.add_path(admin_to_sudo)
        self.add_path(sudo_to_admin)
        self.add_path(prelogin_to_admin)
        self.add_path(admin_to_prelogin)
        self.add_path(fireos_to_admin_path)
        self.add_path(admin_to_fireos_path)
        self.add_path(fireos_to_prelogin)

        # after inactivity timer, it will go back to prelogin:
        self.add_default_statements([self.statements.login_password, self.statements.login_incorrect])
