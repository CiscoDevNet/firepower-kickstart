import re
import time
from unicon.statemachine import State, Path, StateMachine

from unicon.core.errors import StateMachineError
from unicon.statemachine.statetransition import StateTransition, \
    HopWiseStateTransition, AnyStateTransition
from unicon.utils import AttributeDict

from .statements import SspStatements
from .dialogs import SspDialogs


class SspStateMachine(StateMachine):
    """An SSP class that restores all states."""

    def __init__(self, patterns, hostname, deploy_type='native',
                 app_identifier=''):
        """Initializer of SspStateMachine."""

        self.deploy_type = deploy_type
        self.app_identifier = app_identifier
        self.patterns = patterns
        self.dialogs = SspDialogs(patterns, deploy_type)
        self.statements = SspStatements(patterns)
        self.dev_hostname = hostname
        self.states_dict = dict()
        super().__init__(hostname)
        # this is used to group the ftd "application" states
        self.ftd_states = None

    def create(self):
        # Create States and their state patterns

        # FXOS level states
        prelogin_state = State('prelogin_state',
                               self.patterns.prompt.prelogin_prompt)
        mio_state = State('mio_state', self.patterns.prompt.mio_prompt)
        local_mgmt_state = State('local_mgmt_state',
                                 self.patterns.prompt.local_mgmt_prompt)
        fxos_state = State('fxos_state', self.patterns.prompt.fxos_prompt)
        cimc_state = State('cimc_state', self.patterns.prompt.cimc_prompt)

        rommon_state = State('rommon_state',
                             self.patterns.prompt.rommon_prompt)  # ?
        switch_boot_state = State('switch_boot_state',
                                  self.patterns.prompt.switch_boot)  # ?

        # Module level state
        fpr_module_state = State('fpr_module_state',
                                 self.patterns.prompt.fpr_module_prompt)

        # FTD level states
        fireos_state = State('fireos_state', self.patterns.prompt.fireos_prompt)
        expert_state = State('expert_state', self.patterns.prompt.expert_cli)
        sudo_state = State('sudo_state', self.patterns.prompt.sudo_prompt)
        enable_state = State('enable_state', self.patterns.prompt.enable_prompt)
        disable_state = State('disable_state',
                              self.patterns.prompt.disable_prompt)
        config_state = State('config_state', self.patterns.prompt.config_prompt)
        # add new states to the below list also, this is used for the
        # session disconnect handling behavior inside the SspLine go_to
        self.ftd_states = ['fireos_state', 'expert_state', 'sudo_state',
                           'enable_state', 'disable_state', 'config_state']

        # ASA level states
        asa_state = State('asa_state', self.patterns.prompt.asa_prompt)

        # Add states to the state machine
        self.add_state(prelogin_state)
        self.states_dict.update({'prelogin_state': prelogin_state})
        self.add_state(mio_state)
        self.states_dict.update({'mio_state': mio_state})
        self.add_state(local_mgmt_state)
        self.states_dict.update({'local_mgmt_state': local_mgmt_state})
        self.add_state(fxos_state)
        self.states_dict.update({'fxos_state': fxos_state})
        self.add_state(cimc_state)
        self.states_dict.update({'cimc_state': cimc_state})
        self.add_state(fpr_module_state)
        self.states_dict.update({'fpr_module_state': fpr_module_state})
        self.add_state(fireos_state)
        self.states_dict.update({'fireos_state': fireos_state})
        self.add_state(expert_state)
        self.states_dict.update({'expert_state': expert_state})
        self.add_state(sudo_state)
        self.states_dict.update({'sudo_state': sudo_state})
        self.add_state(rommon_state)
        self.states_dict.update({'rommon_state': rommon_state})
        self.add_state(switch_boot_state)
        self.states_dict.update({'switch_boot_state': switch_boot_state})
        self.add_state(asa_state)
        self.states_dict.update({'asa_state': asa_state})
        self.add_state(enable_state)
        self.states_dict.update({'enable_state': enable_state})
        self.add_state(disable_state)
        self.states_dict.update({'disable_state': disable_state})
        self.add_state(config_state)
        self.states_dict.update({'config_state': config_state})

        # Create paths for switching between states
        # Connect from login to MIO
        prelogin_to_mio = Path(prelogin_state, mio_state, 'admin',
                               self.dialogs.d_prelogin_to_mio)
        mio_to_prelogin = Path(mio_state, prelogin_state, 'top; exit', None)

        # Connect from MIO to a blade module boot cli
        mio_to_fpr_module = Path(
            mio_state, fpr_module_state,
            "connect module {} telnet".format(self.patterns.slot_id),
            self.dialogs.d_mio_to_fpr_module)
        if self.deploy_type == 'native':
            mio_to_fpr_module = Path(
                mio_state, fpr_module_state,
                "connect module {} console".format(self.patterns.slot_id),
                self.dialogs.d_mio_to_fpr_module)

        fpr_module_to_mio = Path(fpr_module_state, mio_state, "exit",
                                 self.dialogs.d_fpr_module_to_mio)
        if self.deploy_type == 'native':
            fpr_module_to_mio = Path(fpr_module_state, mio_state, "~",
                                     self.dialogs.d_fpr_module_to_mio)


        # Connect from MIO to local-mgmt
        mio_to_local_mgmt = Path(mio_state, local_mgmt_state,
                                 "connect local-mgmt", None)
        local_mgmt_to_mio = Path(local_mgmt_state, mio_state, "exit", None)

        # Connect from MIO to fxos
        mio_to_fxos = Path(mio_state, fxos_state, "connect fxos", None)
        fxos_to_mio = Path(fxos_state, mio_state, "exit", None)

        # Connect from MIO to blade CIMC
        mio_to_cimc = Path(
            mio_state, cimc_state,
            "connect cimc 1/{}".format(self.patterns.slot_id), None)
        cimc_to_mio = Path(cimc_state, mio_state, "exit", None)

        app_identifier = ''
        if self.deploy_type == 'container':
            app_identifier = self.app_identifier.lower()
        # Connect from blade module boot cli to FTD
        fpr_module_to_ftd = Path(
            fpr_module_state, fireos_state,
            "connect ftd {}".format(app_identifier),
            self.dialogs.d_fpr_module_to_ftd)
        ftd_to_fpr_module = Path(
            fireos_state, fpr_module_state, "exit", None)

        # Connect from FTD to expert mode
        ftd_to_expert = Path(fireos_state, expert_state, "expert", None)
        expert_to_ftd = Path(expert_state, fireos_state, "exit", None)

        # Connect from FTD expert to sudo
        expert_to_sudo = Path(expert_state, sudo_state, "sudo su -",
                              self.dialogs.d_expert_to_sudo)
        sudo_to_expert = Path(sudo_state, expert_state, "exit", None)

        expert_to_disable_path = Path(expert_state, disable_state,
                                      'sudo lina_cli',
                                      self.dialogs.d_expert_to_sudo)
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
        enable_to_disable_state = Path(enable_state, disable_state, "disable",
                                       None)

        disable_to_expert_path = Path(disable_state, expert_state, '\001' + 'd',
                                      self.dialogs.d_disable_to_expert)
        disable_to_fireos_path = Path(disable_state, fireos_state, '\001' + 'd',
                                      self.dialogs.d_disable_to_fireos)
        enable_to_config_path = Path(enable_state, config_state, 'conf t', None)
        config_to_enable_path = Path(config_state, enable_state, 'end', None)

        # Connect from blade module boot cli to ASA
        fpr_module_to_asa = Path(fpr_module_state, asa_state, 'connect asa',
                                 None)
        asa_to_fpr_module = Path(asa_state, fpr_module_state, '\001d', None)

        # Add paths to the State Machine
        # FXOS Level paths
        self.add_path(prelogin_to_mio)
        self.add_path(mio_to_prelogin)
        self.add_path(mio_to_fpr_module)
        self.add_path(fpr_module_to_mio)
        self.add_path(mio_to_local_mgmt)
        self.add_path(local_mgmt_to_mio)
        self.add_path(mio_to_fxos)
        self.add_path(fxos_to_mio)
        self.add_path(mio_to_cimc)
        self.add_path(cimc_to_mio)

        # FTD level paths
        self.add_path(fpr_module_to_ftd)
        self.add_path(ftd_to_fpr_module)
        self.add_path(ftd_to_expert)
        self.add_path(expert_to_ftd)
        self.add_path(expert_to_sudo)
        self.add_path(sudo_to_expert)
        self.add_path(expert_to_disable_path)
        self.add_path(fireos_to_disable_state)
        self.add_path(disable_to_enable_state)
        self.add_path(enable_to_config_path)
        self.add_path(config_to_enable_path)
        self.add_path(enable_to_disable_state)
        self.add_path(disable_to_expert_path)
        self.add_path(disable_to_fireos_path)
        self.add_path(fireos_to_enable_state)
        self.add_path(fireos_to_config_state)

        # ASA level paths
        self.add_path(fpr_module_to_asa)
        self.add_path(asa_to_fpr_module)

        # after inactivity timer, it will go back to prelogin:
        self.add_default_statements(self.statements.login_password)

    def go_to(self, to_state, spawn,
              context=AttributeDict(),
              dialog=None,
              timeout=None,
              hop_wise=False,
              prompt_recovery=False):
        # when a connection is made to the device and the device
        # is left in a random state we need to try to detect the
        # state or signal failure because going to 'any' state
        # can lead to circular transitions which go on in a loop
        # indefinetely
        if self.current_state == 'generic' and to_state is 'any':
            # try to detect in which state we are right now or fail
            # send a newline to initialize the prompt
            output = spawn.expect('.*', timeout=30).match_output
            if output.endswith('\x07'):
                spawn.sendline('\x03')
            # wait 10 seconds for the prompt to populate
            spawn.sendline()
            time.sleep(10)
            # match everything in the output buffer
            output = spawn.expect('.*', timeout=30).match_output
            for state_name, state_data in self.states_dict.items():
                pattern = state_data.pattern
                if isinstance(pattern, str):
                    if re.search(pattern, output):
                        self.update_cur_state(state_name)
                        return output
                if isinstance(pattern, list):
                    for pat in pattern:
                        if re.search(pat, output):
                            self.update_cur_state(state_name)
                            return output
            raise RuntimeError('Could not detect current state. Please ' +
                               'connect to the ssp and bring it to ' +
                               'a valid state clean prompt. Output is: ' +
                               '<BEGIN_OUTPUT>' + output + "<END_OUTPUT>")
        elif (self.current_state != 'generic' and to_state is 'any') or \
                isinstance(to_state, list):
            expected_state = to_state
            transition = AnyStateTransition(state_machine=self,
                                            to_state=to_state,
                                            spawn=spawn,
                                            dialog=dialog,
                                            timeout=timeout,
                                            context=context,
                                            prompt_recovery=prompt_recovery)
        else:
            if not isinstance(to_state, State):
                to_state = self.get_state(to_state)
            expected_state = to_state.name

            # Get the current state from SM
            current_state = self.get_state(self.current_state)

            # If the current and to_state state are same
            # we are already there so just return
            if to_state == current_state:
                return

            # If hop_wise is enabled then do step by step state transition
            if hop_wise:
                transition = HopWiseStateTransition(state_machine=self,
                                                    to_state=to_state,
                                                    spawn=spawn,
                                                    dialog=dialog,
                                                    timeout=timeout,
                                                    context=context,
                                                    prompt_recovery=prompt_recovery)
            else:
                transition = StateTransition(state_machine=self,
                                             to_state=to_state,
                                             spawn=spawn,
                                             dialog=dialog,
                                             timeout=timeout,
                                             context=context,
                                             prompt_recovery=prompt_recovery)
        # Start the state transition
        try:
            output = transition.do_transitions()

        except Exception as err:
            raise StateMachineError('Failed while bringing device to ' +
                                    '"%s" state' % \
                                    str(expected_state)) from err
        finally:
            if transition.current_state is not 'generic':
                self.update_cur_state(transition.current_state)

        # If the current_state and to_state are not matching
        # the probably whe landed somewhere wrong, so raise exception
        if expected_state is not 'any' \
                and self.current_state not in expected_state:
            raise StateMachineError(
                'Changing state to %s failed\n'
                'current_state: %s\n'
                'last command: %s\n'
                'buffer: %s\n'
                'last match: %s' %
                (
                    expected_state,
                    self.current_state,
                    repr(spawn.last_sent),
                    repr(spawn.buffer),
                    repr(spawn.match.match_output)
                )
            )

        return output
