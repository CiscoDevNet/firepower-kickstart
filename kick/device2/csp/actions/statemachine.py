from unicon.statemachine import State, Path, StateMachine
from unicon.eal.dialogs import Dialog
from .statements import CspStatements
from .constants import CspSmStates


class CspStatemachine(StateMachine):
    def __init__(self, patterns):
        self.patterns = patterns
        self.statements = CspStatements(patterns)
        super().__init__()

    def create(self):
        # Create States
        csp_enable_state = State(CspSmStates.CSP_ENABLE_STATE.value, self.patterns.prompt.enable_prompt)
        csp_config_state = State(CspSmStates.CSP_CONFIG_STATE.value, self.patterns.prompt.config_prompt)

        # Add states
        self.add_state(csp_enable_state)
        self.add_state(csp_config_state)

        enable_to_config_path = Path(csp_enable_state, csp_config_state, 'config t', None)
        config_to_enable_path = Path(csp_config_state, csp_enable_state, 'end', None)

        # Add paths
        self.add_path(enable_to_config_path)
        self.add_path(config_to_enable_path)


    def change_pattern(self, new_patterns):

        self.patterns = new_patterns
        self.statements = CspStatements(new_patterns)

        for state in self.states:
            if state.name == CspSmStates.ENABLE_STATE.value:
                state.pattern = self.patterns.prompt.enable_prompt
            elif state.name == CspSmStates.CONFIG_STATE.value:
                state.pattern = self.patterns.prompt.config_prompt
