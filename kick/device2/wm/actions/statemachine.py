from ...kp.actions.statemachine import KpStateMachine
from unicon.statemachine import Path


class WmStateMachine(KpStateMachine):

    def __init__(self, patterns):
        """Initializer of SspStateMachine."""
        super().__init__(patterns)

    def create(self):

        super().create()

        # fireos to fxos transition has changed on child Wm class
        new_path_ftd_to_fxos = Path(self.get_state('fireos_state'), self.get_state('fxos_state'), "exit")

        # Add path to the State Machine
        self.remove_path(self.get_state('fireos_state'), self.get_state('fxos_state'))
        self.add_path(new_path_ftd_to_fxos)
