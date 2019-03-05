from unicon.statemachine import State, Path, StateMachine
from unicon.eal.dialogs import Dialog
from .statements import ElektraStatements
from .dialogs import ElektraDialog


class ElektraStatemachine(StateMachine):
    def __init__(self, patterns):
        """Initializer of SspStateMachine."""
        self.patterns = patterns
        self.dialogs = ElektraDialog(patterns)
        self.statements = ElektraStatements(patterns)

        super().__init__()

    def create(self):
        # Create States
        prelogin_state = State('prelogin_state', self.patterns.prompt.prelogin_prompt)
        fireos_state = State('fireos_state', self.patterns.prompt.fireos_prompt)
        expert_state = State('expert_state', self.patterns.prompt.expert_prompt)
        sudo_state = State('sudo_state', self.patterns.prompt.sudo_prompt)
        disable_state = State('disable_state', self.patterns.prompt.disable_prompt)
        enable_state = State('enable_state', self.patterns.prompt.enable_prompt)
        config_state = State('config_state', self.patterns.prompt.config_prompt)
        rommon_state = State('rommon_state', self.patterns.prompt.rommon_prompt)
        boot_state = State('boot_state', self.patterns.prompt.firepower_boot)

        # Add states
        self.add_state(prelogin_state)
        self.add_state(fireos_state)
        self.add_state(expert_state)
        self.add_state(sudo_state)
        self.add_state(disable_state)
        self.add_state(enable_state)
        self.add_state(config_state)
        self.add_state(rommon_state)
        self.add_state(boot_state)

        # Create paths
        prelogin_to_fireos_path = Path(prelogin_state, fireos_state, 'admin',
                                       Dialog([self.statements.login_password_statement]))
        fireos_to_prelogin_path = Path(fireos_state, prelogin_state, 'exit', None)
        fireos_to_expert_path = Path(fireos_state, expert_state, 'expert', None)
        expert_to_fireos_path = Path(expert_state, fireos_state, 'exit', None)
        expert_to_sudo_path = Path(expert_state, sudo_state, 'sudo su -',
                                   Dialog([self.statements.sudo_password_statement]))
        sudo_to_expert_path = Path(sudo_state, expert_state, 'exit', None)
        expert_to_enable_path = Path(expert_state, enable_state, '\036' + 'x',
                                     Dialog([self.statements.sudo_password_statement]))
        enable_to_expert_path = Path(enable_state, expert_state, 'session sfr console' + '\n', self.dialogs.sfr_dialog)
        disable_to_enable_path = Path(disable_state, enable_state, '',
                                      Dialog([self.statements.enable_password_statement, ]))
        enable_to_disable_path = Path(enable_state, disable_state, 'disable', None)
        enable_to_config_path = Path(enable_state, config_state, 'config t', None)
        config_to_enable_path = Path(config_state, enable_state, 'end', None)
        boot_to_enable_path = Path(boot_state, enable_state, '\036' + 'x',
                                   Dialog([self.statements.sudo_password_statement]))

        # Add paths
        self.add_path(prelogin_to_fireos_path)
        self.add_path(fireos_to_prelogin_path)
        self.add_path(fireos_to_expert_path)
        self.add_path(expert_to_fireos_path)
        self.add_path(expert_to_sudo_path)
        self.add_path(sudo_to_expert_path)
        self.add_path(expert_to_enable_path)
        self.add_path(enable_to_expert_path)
        self.add_path(disable_to_enable_path)
        self.add_path(enable_to_disable_path)
        self.add_path(enable_to_config_path)
        self.add_path(config_to_enable_path)
        self.add_path(boot_to_enable_path)

        # Add a default statement:
        self.add_default_statements(self.statements.enable_password_statement)
