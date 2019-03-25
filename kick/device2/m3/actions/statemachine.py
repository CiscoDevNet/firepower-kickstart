from unicon.statemachine import State, Path, StateMachine
from .statements import M3Statements
from .dialogs import M3Dialogs
from unicon.eal.dialogs import Dialog


class M3Statemachine(StateMachine):
    def __init__(self, patterns):
        """Constructor of state machine for M3."""

        self.patterns = patterns
        self.dialogs = M3Dialogs(self.patterns)
        self.statements = M3Statements(self.patterns)
        super().__init__()

    def create(self):
        # Create States and their state patterns
        prelogin_state = State('prelogin_state', self.patterns.prompt.prelogin_prompt)
        mio_state = State('mio_state', self.patterns.prompt.mio_prompt)
        admin_state = State('admin_state', self.patterns.prompt.admin_prompt)
        sudo_state = State('sudo_state', self.patterns.prompt.sudo_prompt)
        fireos_state = State('fireos_state', self.patterns.prompt.fireos_prompt)
        liloboot_state = State('liloboot_state', self.patterns.prompt.lilo_boot_prompt)
        liloos_state = State('lilos_state', self.patterns.prompt.lilo_os_prompt)
        lilo_boot_menu_state = State('lilobootmenu_state', self.patterns.prompt.lilo_boot_menu_prompt)

        # Add our states to the state machine
        self.add_state(prelogin_state)
        self.add_state(mio_state)
        self.add_state(admin_state)
        self.add_state(sudo_state)
        self.add_state(fireos_state)
        self.add_state(liloboot_state)
        self.add_state(liloos_state)
        self.add_state(lilo_boot_menu_state)

        # Create paths for switching between states
        mio_to_admin = Path(mio_state,
                            admin_state,
                            "connect host",
                            self.dialogs.d_mio_to_admin)
        admin_to_sudo = Path(admin_state,
                             sudo_state,
                             "sudo su -",
                             self.dialogs.d_admin_to_sudo)
        sudo_to_admin = Path(sudo_state, admin_state, "exit", None)
        admin_to_mio = Path(admin_state, mio_state, "\030", None)
        prelogin_to_admin = Path(prelogin_state, admin_state, 'admin',
                                 Dialog([self.statements.login_password_statement]))

        admin_to_prelogin = Path(admin_state, prelogin_state, 'exit', None)

        # transitions from and to 'fireos_state' state
        fireos_to_admin_path = Path(fireos_state, admin_state, 'expert', None)
        admin_to_fireos_path = Path(admin_state, fireos_state, 'exit', None)
        fireos_to_prelogin = Path(fireos_state, prelogin_state, 'exit', None)

        # Add paths to the State Machine
        self.add_path(mio_to_admin)
        self.add_path(admin_to_sudo)
        self.add_path(sudo_to_admin)
        self.add_path(admin_to_mio)
        self.add_path(prelogin_to_admin)
        self.add_path(admin_to_prelogin)
        self.add_path(fireos_to_admin_path)
        self.add_path(admin_to_fireos_path)
        self.add_path(fireos_to_prelogin)

        # after inactivity timer, it will go back to prelogin:
        self.add_default_statements([self.statements.login_password, self.statements.login_incorrect])

