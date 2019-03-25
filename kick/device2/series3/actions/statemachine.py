from unicon.statemachine import State, Path, StateMachine
from unicon.eal.dialogs import Dialog
from .patterns import Series3Patterns
from .statements import Series3Statements
from .dialogs import Series3Dialog


class Series3Statemachine(StateMachine):
    def __init__(self, patterns):
        """Constructor of state machine for ftd series3."""

        self.patterns = patterns
        self.dialog = Series3Dialog(self.patterns)
        self.statements = Series3Statements(self.patterns)
        super().__init__()

    def create(self):
        # Create States and their state patterns
        prelogin_state = State('prelogin_state', self.patterns.prompt.prelogin_prompt)
        fireos_state = State('fireos_state', self.patterns.prompt.fireos_prompt)
        expert_state = State('expert_state', self.patterns.prompt.expert_prompt)
        sudo_state = State('sudo_state', self.patterns.prompt.sudo_prompt)
        eula_state = State('eula_state', self.patterns.prompt.eula_prompt)
        firstboot_state = State('firstboot_state', self.patterns.prompt.firstboot_prompt)
        liloboot_state = State('liloboot_state', self.patterns.prompt.lilo_boot_prompt)
        liloos_state = State('lilos_state', self.patterns.prompt.lilo_os_prompt)
        lilo_boot_menu_state = State('lilobootmenu_state', self.patterns.prompt.lilo_boot_menu_prompt)

        # Add states
        self.add_state(prelogin_state)
        self.add_state(fireos_state)
        self.add_state(expert_state)
        self.add_state(sudo_state)
        self.add_state(eula_state)
        self.add_state(firstboot_state)
        self.add_state(liloboot_state)
        self.add_state(liloos_state)
        self.add_state(lilo_boot_menu_state)

        # Create paths
        fireos_to_expert_path = Path(fireos_state, expert_state, 'expert', None)
        expert_to_fireos_path = Path(expert_state, fireos_state, 'exit', None)
        expert_to_sudo_path = Path(expert_state, sudo_state, 'sudo su -',
                                   Dialog([self.statements.sudo_password_statement]))
        sudo_to_expert_path = Path(sudo_state, expert_state, 'exit', None)
        prelogin_to_fireos = Path(prelogin_state, fireos_state, 'admin',
                                  Dialog([self.statements.login_password_statement]))
        fireos_to_prelogin = Path(fireos_state, prelogin_state, 'exit', None)

        # Add paths
        self.add_path(fireos_to_expert_path)
        self.add_path(expert_to_fireos_path)
        self.add_path(expert_to_sudo_path)
        self.add_path(sudo_to_expert_path)
        self.add_path(prelogin_to_fireos)
        self.add_path(fireos_to_prelogin)

