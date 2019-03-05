from unicon.statemachine import State, Path, StateMachine
from unicon.eal.dialogs import Dialog
from .statements import KvmStatements
from .patterns import Patterns


class KvmStatemachine(StateMachine):

    def create(self):
        # Create States
        prelogin_state = State('prelogin_state', Patterns.prelogin_prompt)
        sudo_state = State('sudo_state', Patterns.sudo_prompt)
        user_state = State('user_state', Patterns.user_prompt)

        # Add states
        self.add_state(prelogin_state)
        self.add_state(sudo_state)
        self.add_state(user_state)

        # Create paths
        prelogin_to_user_path = Path(prelogin_state, user_state, 'cisco',
                                      Dialog([KvmStatements.login_password_statement]))
        user_to_prelogin_path = Path(user_state, prelogin_state, 'exit', None)
        user_to_sudo_path = Path(user_state, sudo_state, 'su -',
                                     Dialog([KvmStatements.sudo_password_statement]))
        sudo_to_user_path = Path(sudo_state, user_state, 'exit', None)
        sudo_to_prelogin_path = Path(sudo_state, prelogin_state, 'exit', None)
        
        # Add paths
        self.add_path(prelogin_to_user_path)
        self.add_path(user_to_prelogin_path)
        self.add_path(user_to_sudo_path)
        self.add_path(sudo_to_user_path)
        self.add_path(sudo_to_prelogin_path)

        # Add a default statement:
        self.add_default_statements(KvmStatements.login_password_statement)
