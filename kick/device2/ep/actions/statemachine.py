from unicon.eal.dialogs import Dialog
from unicon.statemachine import State, Path, StateMachine
from .statements import EpStatements
from .dialogs import EpDialogs


class EpStatemachine(StateMachine):
    def __init__(self, patterns):
        """ Constructor of state machine for EP
        """
        self.patterns = patterns
        self.dialogs = EpDialogs(self.patterns)
        self.statements = EpStatements(self.patterns)
        super().__init__()

    def create(self):
        # Create States and their state patterns
        prelogin_state = State('prelogin_state', self.patterns.prompt.prelogin_prompt)
        admin_state = State('admin_state', self.patterns.prompt.admin_prompt)
        sudo_state = State('sudo_state', self.patterns.prompt.sudo_prompt)

        # Add our states to the state machine
        self.add_state(admin_state)
        self.add_state(sudo_state)
        self.add_state(prelogin_state)

        # Create paths for switching between states
        admin_to_sudo = Path(admin_state, sudo_state, 'sudo su -',
                             self.dialogs.d_admin_to_sudo)

        sudo_to_admin = Path(sudo_state, admin_state, "exit", None)

        prelogin_to_admin = Path(prelogin_state, admin_state, 'admin',
                                 Dialog([self.statements.login_password_statement]))

        admin_to_prelogin = Path(admin_state, prelogin_state, 'exit', None)

        # Add paths to the State Machine
        self.add_path(admin_to_sudo)
        self.add_path(sudo_to_admin)
        self.add_path(prelogin_to_admin)
        self.add_path(admin_to_prelogin)

        # after inactivity timer, it will go back to prelogin:
        self.add_default_statements(self.statements.login_password)
