from unicon.statemachine import State, Path, StateMachine
from .statements import KpStatements
from .patterns import KpPatterns
from .dialogs import KpDialogs

class KpStateMachine(StateMachine):
    """
        Base KpStateMachine. This class is extension of Unicon's StateMachine
        that aims to provide the functionality of interacting with FXOS, Rommon, 
        and Lina cli's.
    """
    def __init__(self, patterns):
        """Initializer of SspStateMachine."""

        self.patterns = patterns
        self.dialogs = KpDialogs(patterns)
        self.statements = KpStatements(patterns)
        super().__init__()

    def create(self):
        # Create States and their state patterns
        fxos_state = State('fxos_state', self.patterns.prompt.fxos_prompt)
        fireos_state = State('fireos_state', self.patterns.prompt.fireos_prompt)
        expert_state = State('expert_state', self.patterns.prompt.expert_prompt)
        sudo_state = State('sudo_state', self.patterns.prompt.sudo_prompt)
        rommon_state = State('rommon_state', self.patterns.prompt.rommon_prompt)
        local_mgmt_state = State('local_mgmt_state', self.patterns.prompt.local_mgmt_prompt)

        # lina cli states
        enable_state = State('enable_state', self.patterns.prompt.enable_prompt)
        disable_state = State('disable_state', self.patterns.prompt.disable_prompt)
        config_state = State('config_state', self.patterns.prompt.config_prompt)

        # Add our states to the state machine
        self.add_state(fxos_state)
        self.add_state(fireos_state)
        self.add_state(expert_state)
        self.add_state(sudo_state)
        self.add_state(rommon_state)
        self.add_state(local_mgmt_state)
        self.add_state(enable_state)
        self.add_state(disable_state)
        self.add_state(config_state)

        # Create paths for switching between states        
        fxos_to_ftd = Path(fxos_state, fireos_state, "connect ftd", None)
        fxos_to_local_mgmt = Path(fxos_state, local_mgmt_state, "connect local-mgmt", None)
        ftd_to_expert = Path(fireos_state, expert_state, "expert", None)
        ftd_expert_to_sudo = Path(expert_state, sudo_state, "sudo su -", self.dialogs.d_expert_to_sudo)
        ftd_sudo_to_expert = Path(sudo_state, expert_state, "exit", None)
        expert_to_ftd = Path(expert_state, fireos_state, "exit", None)
        local_mgmt_to_fxos = Path(local_mgmt_state, fxos_state, "exit", None)
        # there are two paths from fireos_state to fxos_state.
        # 1. if on console, type "exit". if you type "connect fxos" you will be prompted to use "exit".
        # 2. if on mgmt vty, type "connect fxos". if you type "exit", you will lose the vty.
        # the following dialog tries "connect fxos" first, if prompted, uses "exit". it should work on both.
        ftd_to_fxos = Path(fireos_state, fxos_state, "connect fxos", self.dialogs.d_ftd_to_fxos)

        # Create lina cli paths
        enable_to_disable_state = Path(enable_state, disable_state, "disable", None)
        enable_to_config_path = Path(enable_state, config_state, 'conf t', None)
        config_to_enable_path = Path(config_state, enable_state, 'end', None)        

        # Add paths to the State Machine
        self.add_path(fxos_to_ftd)
        self.add_path(ftd_to_fxos)
        self.add_path(fxos_to_local_mgmt)
        self.add_path(local_mgmt_to_fxos)
        self.add_path(ftd_to_expert)
        self.add_path(expert_to_ftd)
        self.add_path(ftd_expert_to_sudo)
        self.add_path(ftd_sudo_to_expert)
        self.add_path(enable_to_disable_state)
        self.add_path(enable_to_config_path)
        self.add_path(config_to_enable_path)

        # after inactivity timer, it will go back to prelogin:
        self.add_default_statements([self.statements.login_incorrect, self.statements.login_password])

class KpFtdStateMachine(KpStateMachine):
    """
        FTD-friendly Extension of KpStateMachine. 

        This extension aims to support the 'enable-state' exclusive to FTD.

        Only supports FTD <--> FTD baselining.
    """
    def __init__(self, patterns):
        """Initializer of KpStateMachine."""
        super().__init__(patterns)

    def create(self):
        super().create()
        disable_to_enable_state = Path(self.get_state('disable_state'), 
                                       self.get_state('enable_state'), 
                                       'en',
                                       self.dialogs.ftd_dialogs.disable_to_enable)
        fireos_to_disable_state = Path(self.get_state('fireos_state'), 
                                       self.get_state('disable_state'),
                                       'system support diagnostic-cli',
                                       None)
        disable_to_fireos_path = Path(self.get_state('disable_state'),
                                      self.get_state('fireos_state'),  
                                      '\001'+'d'+'exit',
                                      None)

        self.add_path(fireos_to_disable_state)
        self.add_path(disable_to_fireos_path)
        self.add_path(disable_to_enable_state)

class KpAsaStateMachine(KpStateMachine):
    """
        ASA-friendly Extension of KpStateMachine. Because of this inheritance,
        it will still work with the common states of both FTD and ASA, e.g.
        (FXOS, Rommon, etc.)  
        
        This extension aims to support the 'enable-state' of ASA. 

        Supports all combinations of FTD <--> ASA baselining.

        Note that if you want to used FTD's enable state after baselining from
        ASA, you will need to create a new KP object with 'use_asa' set to 
        False. This will instantiate a FTD friendly statemachine. 
    """
    def __init__(self, patterns):
        """Initializer of KpStateMachine."""
        super().__init__(patterns)

    def create(self):
        super().create()
        disable_to_enable_state = Path(self.get_state('disable_state'), 
                                       self.get_state('enable_state'), 
                                       'en',
                                       self.dialogs.disable_to_enable)
        enable_to_fxos_path = Path(self.get_state('enable_state'), 
                                   self.get_state('fxos_state'), 
                                   'connect fxos admin',
                                    None)
        fxos_to_enable_path = Path(self.get_state('fxos_state'), 
                                   self.get_state('enable_state'), 
                                   'exit', 
                                   None)

        self.add_path(enable_to_fxos_path)
        self.add_path(fxos_to_enable_path)
        self.add_path(disable_to_enable_state)
