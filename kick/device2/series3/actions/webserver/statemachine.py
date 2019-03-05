from unicon.statemachine import State, Path, StateMachine
from .patterns import WebserverPatterns


class WebserverStatemachine(StateMachine):
    def create(self):
        # Create States
        user_state = State('user_state', WebserverPatterns.user_prompt)
        # Add states
        self.add_state(user_state)

        # Create paths
        # Add paths

