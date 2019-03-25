from unicon.statemachine import State, Path, StateMachine
from unicon.eal.dialogs import Dialog
from .statements import AsaStatements
from .constants import AsaSmStates


class AsaStatemachine(StateMachine):
    def __init__(self, patterns):
        self.patterns = patterns
        self.statements = AsaStatements(patterns)
        super().__init__()

    def create(self):
        # Create States
        disable_state = State(AsaSmStates.DISABLE_STATE.value, self.patterns.prompt.disable_prompt)
        enable_state = State(AsaSmStates.ENABLE_STATE.value, self.patterns.prompt.enable_prompt)
        config_state = State(AsaSmStates.CONFIG_STATE.value, self.patterns.prompt.config_prompt)

        # Add states
        self.add_state(disable_state)
        self.add_state(enable_state)
        self.add_state(config_state)

        # Create paths
        enable_dialog = Dialog(
            [self.statements.disable_to_enable_statement,
             self.statements.set_enable_pwd_statement,
             self.statements.repeat_enable_pwd_statement,
            ]
        )
        disable_to_enable_path = Path(disable_state, enable_state, 'enable', enable_dialog)
        enable_to_disable_path = Path(enable_state, disable_state, 'disable', None)
        enable_to_config_path = Path(enable_state, config_state, 'config t', None)
        config_to_enable_path = Path(config_state, enable_state, 'end', None)

        # Add paths
        self.add_path(disable_to_enable_path)
        self.add_path(enable_to_disable_path)
        self.add_path(enable_to_config_path)
        self.add_path(config_to_enable_path)

    def change_pattern(self, new_patterns):
        self.patterns = new_patterns
        self.statements = AsaStatements(new_patterns)
        for state in self.states:
            if state.name == AsaSmStates.DISABLE_STATE.value:
                state.pattern = self.patterns.prompt.disable_prompt
            elif state.name == AsaSmStates.ENABLE_STATE.value:
                state.pattern = self.patterns.prompt.enable_prompt
            elif state.name == AsaSmStates.CONFIG_STATE.value:
                state.pattern = self.patterns.prompt.config_prompt
        for path in self.paths:
            if repr(path) == "%s->%s" % (AsaSmStates.DISABLE_STATE.value, AsaSmStates.ENABLE_STATE.value):
                path.dialog = Dialog([self.statements.disable_to_enable_statement, ])