from unicon.statemachine import State, Path, StateMachine
from unicon.eal.dialogs import Dialog
from .patterns import Elektra5585Patterns
from .statements import Elektra5585Statements
from .dialogs import Elektra5585Dialog


class Elektra5585Statemachine(StateMachine):
    def __init__(self, patterns):
        """Initializer of Elektra5585StateMachine."""
        self.patterns = patterns
        self.dialogs = Elektra5585Dialog(patterns)
        self.statements = Elektra5585Statements(patterns)

        super().__init__()

    def create(self):
        # Create States
        prelogin_state = State('prelogin_state', self.patterns.prompt.prelogin_prompt)
        pkglogin_state = State('pkglogin_state', self.patterns.prompt.pkglogin_prompt)
        fireos_state = State('fireos_state', self.patterns.prompt.fireos_prompt)
        expert_state = State('expert_state', self.patterns.prompt.expert_prompt)
        sudo_state = State('sudo_state', self.patterns.prompt.sudo_prompt)
        rommon_state = State('rommon_state', self.patterns.prompt.rommon_prompt)
        boot_state = State('boot_state', self.patterns.prompt.firepower_boot)
        config_state = State('config_state', self.patterns.prompt.config_prompt)
        system_state = State('system_state', self.patterns.prompt.system_prompt)

        # Add states
        self.add_state(prelogin_state)
        self.add_state(pkglogin_state)
        self.add_state(fireos_state)
        self.add_state(expert_state)
        self.add_state(sudo_state)
        self.add_state(rommon_state)
        self.add_state(boot_state)
        self.add_state(config_state)
        self.add_state(system_state)

        # Create paths
        prelogin_to_fireos_path = Path(prelogin_state, fireos_state, 'admin',
                                       Dialog([self.statements.login_password_statement]))
        pkglogin_to_boot_path = Path(pkglogin_state, boot_state, 'admin',
                                       Dialog([self.statements.pkg_password_statement]))
        fireos_to_prelogin_path = Path(fireos_state, prelogin_state, 'exit', None)
        fireos_to_expert_path = Path(fireos_state, expert_state, 'expert', None)
        expert_to_fireos_path = Path(expert_state, fireos_state, 'exit', None)
        expert_to_sudo_path = Path(expert_state, sudo_state, 'sudo su -',
                                   Dialog([self.statements.sudo_password_statement]))
        sudo_to_expert_path = Path(sudo_state, expert_state, 'exit', None)
        system_to_expert_path = Path(system_state, expert_state, 'expert', None)
        expert_to_system_path = Path(expert_state, system_state, 'exit', None)

        # Add paths
        self.add_path(prelogin_to_fireos_path)
        self.add_path(pkglogin_to_boot_path)
        self.add_path(fireos_to_prelogin_path)
        self.add_path(fireos_to_expert_path)
        self.add_path(expert_to_fireos_path)
        self.add_path(expert_to_sudo_path)
        self.add_path(sudo_to_expert_path)
        self.add_path(system_to_expert_path)
        self.add_path(expert_to_system_path)
