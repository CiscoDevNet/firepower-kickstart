from unicon.statemachine import State, Path, StateMachine
from unicon.eal.dialogs import Dialog
from .patterns import Ftd5500xPatterns
from .statements import Ftd5500xStatements
from .dialogs import Ftd5500xDialog


class Ftd5500xStatemachine(StateMachine):
    def __init__(self, patterns):
        """Initializer of FtdStateMachine."""
        self.patterns = patterns
        self.dialogs = Ftd5500xDialog(patterns)
        self.statements = Ftd5500xStatements(patterns)

        super().__init__()

    def create(self):
        # Create States
        prelogin_state = State('prelogin_state', self.patterns.prompt.prelogin_prompt)
        fireos_state = State('fireos_state', self.patterns.prompt.fireos_prompt)
        expert_state = State('expert_state', self.patterns.prompt.expert_prompt)
        sudo_state = State('sudo_state', self.patterns.prompt.sudo_prompt)
        enable_state = State('enable_state', self.patterns.prompt.enable_prompt)
        ciscoasa_state = State('ciscoasa_state', self.patterns.prompt.ciscoasa_prompt)
        rommon_state = State('rommon_state', self.patterns.prompt.rommon_prompt)
        boot_state = State('boot_state', self.patterns.prompt.firepower_boot)
        disable_state = State('disable_state', self.patterns.prompt.disable_prompt)
        config_state = State('config_state', self.patterns.prompt.config_prompt)
        system_state = State('system_state', self.patterns.prompt.system_prompt)

        # Add states
        self.add_state(prelogin_state)
        self.add_state(fireos_state)
        self.add_state(expert_state)
        self.add_state(sudo_state)
        self.add_state(enable_state)
        self.add_state(ciscoasa_state)
        self.add_state(rommon_state)
        self.add_state(boot_state)
        self.add_state(disable_state)
        self.add_state(config_state)
        self.add_state(system_state)

        # Create paths
        prelogin_to_fireos_path = Path(prelogin_state, fireos_state, 'admin',
                                       Dialog([self.statements.login_password_statement]))
        fireos_to_prelogin_path = Path(fireos_state, prelogin_state, 'exit', None)
        fireos_to_expert_path = Path(fireos_state, expert_state, 'expert', None)
        expert_to_fireos_path = Path(expert_state, fireos_state, 'exit', None)
        expert_to_sudo_path = Path(expert_state, sudo_state, 'sudo su -',
                                   Dialog([self.statements.sudo_password_statement]))
        sudo_to_expert_path = Path(sudo_state, expert_state, 'exit', None)

        ciscoasa_state_to_sudo_state = Path(ciscoasa_state, sudo_state, 'sudo su -',
                                            Dialog([self.statements.sudo_password_statement]))
        fireos_to_ciscoasa_state = Path(fireos_state, ciscoasa_state, 'expert', None)

        # lina cli paths
        expert_to_disable_path = Path(expert_state, disable_state, 'sudo lina_cli',
                                      self.dialogs.d_expert_to_disable)
        fireos_to_disable_state = Path(fireos_state, disable_state,
                                       'system support diagnostic-cli',
                                       self.dialogs.d_enable_to_disable)
        fireos_to_enable_state = Path(fireos_state, enable_state,
                                      'system support diagnostic-cli',
                                      self.dialogs.d_disable_to_enable)
        fireos_to_config_state = Path(fireos_state, config_state,
                                      'system support diagnostic-cli',
                                      self.dialogs.d_endisable_to_conft)
        disable_to_enable_state = Path(disable_state, enable_state, 'en',
                                       self.dialogs.disable_to_enable)
        enable_to_disable_state = Path(enable_state, disable_state, "disable", None)

        disable_to_fireos_path = Path(disable_state, fireos_state, '\001'+'d'+'exit',
                                      None)

        enable_to_config_path = Path(enable_state, config_state, 'conf t', None)
        config_to_enable_path = Path(config_state, enable_state, 'end', None)

        # system paths
        system_to_expert_path = Path(system_state, expert_state, 'expert', None)
        expert_to_system_path = Path(expert_state, system_state, 'exit', None)

        # Add paths
        self.add_path(prelogin_to_fireos_path)
        self.add_path(fireos_to_prelogin_path)
        self.add_path(fireos_to_expert_path)
        self.add_path(expert_to_fireos_path)
        self.add_path(expert_to_sudo_path)
        self.add_path(sudo_to_expert_path)
        self.add_path(expert_to_disable_path)
        self.add_path(disable_to_fireos_path)
        self.add_path(ciscoasa_state_to_sudo_state)
        self.add_path(fireos_to_ciscoasa_state)
        self.add_path(fireos_to_disable_state)
        self.add_path(disable_to_enable_state)
        self.add_path(enable_to_config_path)
        self.add_path(config_to_enable_path)
        self.add_path(system_to_expert_path)
        self.add_path(expert_to_system_path)
        self.add_path(fireos_to_config_state)
        self.add_path(fireos_to_enable_state)
        self.add_path(enable_to_disable_state)

        # Add a default statement:
        self.add_default_statements(self.statements.enable_password_statement)
