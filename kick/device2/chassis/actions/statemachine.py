'''
In order to understand the state machine, the states and the paths
between the states is it very trivial to place a breakpoint after the
state machine has been constructed and use self.sm.dotgraph() call to
get the state machine representation. This representation can then be
placed in a text file and using dot.exe from Graphviz a visual representation
of the state machine can be created by issueing
<graphviz_bin_folder>\dot.exe -T png -o sm.png sm.dot
The visual representation will be provided in sm.png file and the input should
be provided in sm.dot (from the output of self.sm.dotgraph() call
'''
import re

import time
from unicon.statemachine import State, Path, StateMachine
from unicon.core.errors import StateMachineError
from unicon.statemachine.statetransition import StateTransition, \
    HopWiseStateTransition, AnyStateTransition
from unicon.utils import AttributeDict

from .statements import ChassisStatements
from .dialogs import ChassisDialogs
from unicon.eal.dialogs import Dialog


class ChassisStateMachine(StateMachine):
    def __init__(self, patterns, hostname, chassis_data):
        self.patterns = patterns
        self.current_slot = '1'
        self.current_application = None
        self.dialogs = ChassisDialogs(patterns, chassis_data)
        self.statements = ChassisStatements(patterns, chassis_data)
        self.chassis_software = chassis_data['custom']['chassis_software']
        self.states_dict = dict()
        self.paths_dict = dict()
        self.ftd_states = dict()
        self.states_dependent_on_slot_only = list()
        self.states_dependent_on_slot_and_app = list()
        super().__init__(hostname)

    def add_states_to_state_machine(self):
        for key in self.states_dict:
            self.add_state(self.states_dict[key])

    def add_paths_to_state_machine(self):
        for key in self.paths_dict:
            self.add_path(self.paths_dict[key])

    def define_chassis_level_states(self):
        available_slots = self.get_available_slots()
        self.states_dict.update({
            'prelogin_state': State('prelogin_state',
                                    self.patterns.prompt.prelogin_prompt)
        })
        self.states_dict.update({
            'mio_state': State('mio_state', self.patterns.prompt.mio_prompt)
        })
        self.states_dict.update({
            'local_mgmt_state': State('local_mgmt_state',
                                      self.patterns.prompt.local_mgmt_prompt)
        })
        self.states_dict.update({
            'fxos_state': State('fxos_state', self.patterns.prompt.fxos_prompt)
        })
        for slot in available_slots:
            state_name = 'slot_' + slot + '_cimc_state'
            self.states_dict.update({
                state_name: State(state_name, self.patterns.prompt.cimc_prompt)
            })

    def define_security_module_level_states(self):
        available_slots = self.get_available_slots()
        for slot in available_slots:
            state_name = 'slot_' + slot + '_fpr_module_state'
            self.states_dict.update({
                state_name: State(state_name,
                                  self.patterns.prompt.fpr_module_prompt)
            })

    def define_ftd_level_states(self):
        self._define_ftd_fireos_states()
        self._define_ftd_expert_states()
        self._define_ftd_sudo_states()
        self._define_ftd_enable_states()
        self._define_ftd_disable_states()
        self._define_ftd_config_states()

    def _define_ftd_fireos_states(self):
        available_slots = self.get_available_slots()
        for slot in available_slots:
            available_ftds_on_slot = self.get_available_ftds_on_slot(slot)
            for ftd_app in available_ftds_on_slot:
                state_name = 'slot_' + slot + '_' + ftd_app[
                    'application_identifier'] + '_fireos_state'
                self.states_dict.update({
                    state_name: State(state_name,
                                      self.patterns.prompt.fireos_prompt)
                })

    def _define_ftd_expert_states(self):
        available_slots = self.get_available_slots()
        for slot in available_slots:
            available_ftds_on_slot = self.get_available_ftds_on_slot(slot)
            for ftd_app in available_ftds_on_slot:
                state_name = 'slot_' + slot + '_' + ftd_app[
                    'application_identifier'] + '_expert_state'
                self.states_dict.update({
                    state_name: State(state_name,
                                      self.patterns.prompt.expert_cli)
                })

    def _define_ftd_sudo_states(self):
        available_slots = self.get_available_slots()
        for slot in available_slots:
            available_ftds_on_slot = self.get_available_ftds_on_slot(slot)
            for ftd_app in available_ftds_on_slot:
                state_name = 'slot_' + slot + '_' + ftd_app[
                    'application_identifier'] + '_sudo_state'
                self.states_dict.update({
                    state_name: State(state_name,
                                      self.patterns.prompt.sudo_prompt)
                })

    def _define_ftd_enable_states(self):
        available_slots = self.get_available_slots()
        for slot in available_slots:
            available_ftds_on_slot = self.get_available_ftds_on_slot(slot)
            for ftd_app in available_ftds_on_slot:
                state_name = 'slot_' + slot + '_' + ftd_app[
                    'application_identifier'] + '_enable_state'
                self.states_dict.update({
                    state_name: State(state_name,
                                      self.patterns.prompt.enable_prompt)
                })

    def _define_ftd_disable_states(self):
        available_slots = self.get_available_slots()
        for slot in available_slots:
            available_ftds_on_slot = self.get_available_ftds_on_slot(slot)
            for ftd_app in available_ftds_on_slot:
                state_name = 'slot_' + slot + '_' + ftd_app[
                    'application_identifier'] + '_disable_state'
                self.states_dict.update({
                    state_name: State(state_name,
                                      self.patterns.prompt.disable_prompt)
                })

    def _define_ftd_config_states(self):
        available_slots = self.get_available_slots()
        for slot in available_slots:
            available_ftds_on_slot = self.get_available_ftds_on_slot(slot)
            for ftd_app in available_ftds_on_slot:
                state_name = 'slot_' + slot + '_' + ftd_app[
                    'application_identifier'] + '_config_state'
                self.states_dict.update({
                    state_name: State(state_name,
                                      self.patterns.prompt.config_prompt)
                })

    def define_asa_level_states(self):
        available_slots = self.get_available_slots()
        for slot in available_slots:
            state_name = 'slot_' + slot + '_asa_state'
            self.states_dict.update({
                state_name: State(state_name, self.patterns.prompt.asa_prompt)
            })

    def define_chassis_level_paths(self):
        self._define_chassis_login_paths()
        self._define_chassis_to_security_module_paths()

    def _define_chassis_login_paths(self):
        self.paths_dict.update({
            'prelogin_to_mio': Path(self.states_dict['prelogin_state'],
                                    self.states_dict['mio_state'], 'admin',
                                    self.dialogs.d_prelogin_to_mio)
        })
        self.paths_dict.update({
            'mio_to_prelogin': Path(self.states_dict['mio_state'],
                                    self.states_dict['prelogin_state'],
                                    'top; exit', None)
        })

    def _define_chassis_to_security_module_paths(self):
        fpr_module_states = [key for key in self.states_dict
                             if key.endswith('fpr_module_state')]
        for fpr_module_state in fpr_module_states:
            slot = fpr_module_state[:6].replace('slot_', '')
            console = 'telnet'
            available_ftds_on_slot = self.get_available_ftds_on_slot(slot)
            if available_ftds_on_slot[0]['deploy_type'] == 'native':
                console = 'console'
            self.paths_dict.update({
                'mio_to_' + fpr_module_state: Path(
                    self.states_dict['mio_state'],
                    self.states_dict[fpr_module_state],
                    "connect module {} {}".format(
                        fpr_module_state.replace(
                            'slot_', '').replace('_fpr_module_state', ''),
                        console),
                    self.dialogs.d_mio_to_fpr_module)
            })
            self.paths_dict.update({
                fpr_module_state + '_to_mio': Path(
                    self.states_dict[fpr_module_state],
                    self.states_dict['mio_state'],
                    "exit", self.dialogs.d_fpr_module_to_mio)
            })
        self.paths_dict.update({
            'mio_to_local_mgmt': Path(
                self.states_dict['mio_state'],
                self.states_dict['local_mgmt_state'],
                "connect local-mgmt", None)
        })
        self.paths_dict.update({
            'local_mgmt_to_mio': Path(
                self.states_dict['local_mgmt_state'],
                self.states_dict['mio_state'],
                "exit", None)
        })
        self.paths_dict.update({
            'mio_to_fxos': Path(
                self.states_dict['mio_state'],
                self.states_dict['fxos_state'],
                "connect fxos", None)
        })
        self.paths_dict.update({
            'fxos_to_mio': Path(
                self.states_dict['fxos_state'],
                self.states_dict['mio_state'],
                "exit", None)
        })
        cimc_states = [key for key in self.states_dict
                       if key.endswith('cimc_state')]
        for cimc_state in cimc_states:
            self.paths_dict.update({
                'mio_to_' + cimc_state: Path(
                    self.states_dict['mio_state'],
                    self.states_dict[cimc_state],
                    "connect cimc 1/{}".format(
                        cimc_state.replace('slot_', '').replace(
                            '_cimc_state', '')), None)
            })
            self.paths_dict.update({
                cimc_state + '_to_mio': Path(
                    self.states_dict[cimc_state],
                    self.states_dict['mio_state'],
                    "exit", None)
            })

    def define_ftd_level_paths(self):
        self._define_fpr_to_fireos_paths()
        self._define_fireos_to_expert_paths()
        self._define_expert_to_sudo_paths()
        self._define_expert_to_disable_paths()
        self._define_fireos_to_disable_paths()
        self._define_fireos_to_enable_paths()
        self._define_fireos_to_config_paths()
        self._define_enable_to_disable_paths()
        self._define_enable_to_config_paths()

    def define_asa_level_paths(self):
        fpr_module_states = [key for key in self.states_dict
                             if key.endswith('fpr_module_state')]
        asa_states = [key for key in self.states_dict
                      if key.endswith('asa_state')]
        for fpr_module_state in fpr_module_states:
            for asa_state in asa_states:
                if asa_state.startswith(
                        fpr_module_state.replace('fpr_module_state', '')):
                    fpr_module_to_asa = Path(
                        self.states_dict[fpr_module_state],
                        self.states_dict[asa_state],
                        "connect asa", None)
                    asa_to_fpr_module = Path(
                        self.states_dict[asa_state],
                        self.states_dict[fpr_module_state],
                        '\001d', None)
                    self.paths_dict.update({
                        fpr_module_state + '_to_' +
                        asa_state: fpr_module_to_asa
                    })
                    self.paths_dict.update({
                        asa_state + '_to_' +
                        fpr_module_state: asa_to_fpr_module
                    })

    def _define_fpr_to_fireos_paths(self):
        fpr_module_states = [key for key in self.states_dict
                             if key.endswith('fpr_module_state')]
        fireos_states = [key for key in self.states_dict
                         if key.endswith('fireos_state')]
        for fpr_module_state in fpr_module_states:
            for fireos_state in fireos_states:
                if fireos_state.startswith(
                        fpr_module_state.replace('fpr_module_state', '')):
                    slot = fpr_module_state[:6].replace('slot_', '')
                    current_app_identifier = fireos_state.replace(
                        '_fireos_state', '').split('_')[-1]
                    app_identifier = ''
                    for app in self.get_available_ftds_on_slot(slot):
                        if app['application_identifier'] == \
                                current_app_identifier:
                            if app['deploy_type'] == 'container':
                                app_identifier = current_app_identifier
                            break
                    fpr_module_to_ftd = Path(
                        self.states_dict[fpr_module_state],
                        self.states_dict[fireos_state],
                        "connect ftd {}".format(app_identifier),
                        self.dialogs.d_fpr_module_to_ftd)
                    ftd_to_fpr_module = Path(
                        self.states_dict[fireos_state],
                        self.states_dict[fpr_module_state],
                        "exit", None)
                    self.paths_dict.update({
                        fpr_module_state + '_to_' +
                        fireos_state: fpr_module_to_ftd
                    })
                    self.paths_dict.update({
                        fireos_state + '_to_' +
                        fpr_module_state: ftd_to_fpr_module
                    })

    def _define_fireos_to_expert_paths(self):
        fireos_states = [key for key in self.states_dict
                         if key.endswith('fireos_state')]
        expert_states = [key for key in self.states_dict
                         if key.endswith('expert_state')]
        for fireos_state in fireos_states:
            for expert_state in expert_states:
                if fireos_state.replace('fireos_state', '') \
                        == expert_state.replace('expert_state', ''):
                    fireos_to_expert = Path(
                        self.states_dict[fireos_state],
                        self.states_dict[expert_state],
                        "expert", None)
                    expert_to_fireos = Path(
                        self.states_dict[expert_state],
                        self.states_dict[fireos_state],
                        "exit", None)
                    self.paths_dict.update({
                        fireos_state + '_to_' + expert_state: fireos_to_expert
                    })
                    self.paths_dict.update({
                        expert_state + '_to_' + fireos_state: expert_to_fireos
                    })

    def _define_expert_to_sudo_paths(self):
        expert_states = [key for key in self.states_dict
                         if key.endswith('expert_state')]
        sudo_states = [key for key in self.states_dict
                       if key.endswith('sudo_state')]
        for expert_state in expert_states:
            for sudo_state in sudo_states:
                if expert_state.replace('expert_state', '') \
                        == sudo_state.replace('sudo_state', ''):
                    expert_to_sudo = Path(
                        self.states_dict[expert_state],
                        self.states_dict[sudo_state],
                        "sudo su -", self.dialogs.d_expert_to_sudo)
                    sudo_to_expert = Path(
                        self.states_dict[sudo_state],
                        self.states_dict[expert_state],
                        "exit", None)
                    self.paths_dict.update({
                        expert_state + '_to_' + sudo_state: expert_to_sudo
                    })
                    self.paths_dict.update({
                        sudo_state + '_to_' + expert_state: sudo_to_expert
                    })

    def _define_expert_to_disable_paths(self):
        expert_states = [key for key in self.states_dict
                         if key.endswith('expert_state')]
        disable_states = [key for key in self.states_dict
                          if key.endswith('disable_state')]
        for expert_state in expert_states:
            for disable_state in disable_states:
                if expert_state.replace('expert_state', '') \
                        == disable_state.replace('disable_state', ''):
                    expert_to_disable = Path(
                        self.states_dict[expert_state],
                        self.states_dict[disable_state],
                        'sudo lina_cli', self.dialogs.d_expert_to_sudo)
                    disable_to_expert = Path(
                        self.states_dict[disable_state],
                        self.states_dict[expert_state],
                        '\001' + 'd', self.dialogs.d_disable_to_expert)
                    self.paths_dict.update({
                        expert_state + '_to_' + disable_state: expert_to_disable
                    })
                    self.paths_dict.update({
                        disable_state + '_to_' + expert_state: disable_to_expert
                    })

    def _define_fireos_to_disable_paths(self):
        fireos_states = [key for key in self.states_dict
                         if key.endswith('fireos_state')]
        disable_states = [key for key in self.states_dict
                          if key.endswith('disable_state')]
        for fireos_state in fireos_states:
            for disable_state in disable_states:
                if fireos_state.replace('fireos_state', '') \
                        == disable_state.replace('disable_state', ''):
                    fireos_to_disable = Path(
                        self.states_dict[fireos_state],
                        self.states_dict[disable_state],
                        'system support diagnostic-cli',
                        self.dialogs.d_enable_to_disable)
                    disable_to_fireos = Path(
                        self.states_dict[disable_state],
                        self.states_dict[fireos_state],
                        '\001' + 'd', self.dialogs.d_disable_to_fireos)
                    self.paths_dict.update({
                        fireos_state + '_to_' + disable_state: fireos_to_disable
                    })
                    self.paths_dict.update({
                        disable_state + '_to_' + fireos_state: disable_to_fireos
                    })

    def _define_fireos_to_enable_paths(self):
        fireos_states = [key for key in self.states_dict
                         if key.endswith('fireos_state')]
        enable_states = [key for key in self.states_dict
                         if key.endswith('enable_state')]
        for fireos_state in fireos_states:
            for enable_state in enable_states:
                if fireos_state.replace('fireos_state', '') \
                        == enable_state.replace('enable_state', ''):
                    fireos_to_enable = Path(
                        self.states_dict[fireos_state],
                        self.states_dict[enable_state],
                        'system support diagnostic-cli',
                        self.dialogs.d_disable_to_enable)
                    self.paths_dict.update({
                        fireos_state + '_to_' + enable_state: fireos_to_enable
                    })

    def _define_fireos_to_config_paths(self):
        fireos_states = [key for key in self.states_dict
                         if key.endswith('fireos_state')]
        config_states = [key for key in self.states_dict
                         if key.endswith('config_state')]
        for fireos_state in fireos_states:
            for config_state in config_states:
                if fireos_state.replace('fireos_state', '') \
                        == config_state.replace('config_state', ''):
                    fireos_to_config = Path(
                        self.states_dict[fireos_state],
                        self.states_dict[config_state],
                        'system support diagnostic-cli',
                        self.dialogs.d_endisable_to_conft)
                    self.paths_dict.update({
                        fireos_state + '_to_' + config_state: fireos_to_config
                    })

    def _define_enable_to_disable_paths(self):
        enable_states = [key for key in self.states_dict
                         if key.endswith('enable_state')]
        disable_states = [key for key in self.states_dict
                          if key.endswith('disable_state')]
        for enable_state in enable_states:
            for disable_state in disable_states:
                if enable_state.replace('enable_state', '') \
                        == disable_state.replace('disable_state', ''):
                    enable_to_disable = Path(
                        self.states_dict[enable_state],
                        self.states_dict[disable_state],
                        "disable", None)
                    disable_to_enable = Path(
                        self.states_dict[disable_state],
                        self.states_dict[enable_state],
                        'en', self.dialogs.disable_to_enable)
                    self.paths_dict.update({
                        enable_state + '_to_' + disable_state: enable_to_disable
                    })
                    self.paths_dict.update({
                        disable_state + '_to_' + enable_state: disable_to_enable
                    })

    def _define_enable_to_config_paths(self):
        enable_states = [key for key in self.states_dict
                         if key.endswith('enable_state')]
        config_states = [key for key in self.states_dict
                         if key.endswith('config_state')]
        for enable_state in enable_states:
            for config_state in config_states:
                if enable_state.replace('enable_state', '') \
                        == config_state.replace('config_state', ''):
                    enable_to_config = Path(
                        self.states_dict[enable_state],
                        self.states_dict[config_state],
                        'conf t', None)
                    config_to_enable = Path(
                        self.states_dict[config_state],
                        self.states_dict[enable_state],
                        'end', None)
                    self.paths_dict.update({
                        enable_state + '_to_' + config_state: enable_to_config
                    })
                    self.paths_dict.update({
                        config_state + '_to_' + enable_state: config_to_enable
                    })

    def get_available_slots(self):
        populated_slots = \
            [str(app_data['slot'])
             for app_key, app_data in self.chassis_software[
                 'applications'].items()]
        return list(set(populated_slots))

    def get_available_ftds_on_slot(self, slot):
        return [app_data
                for app_key, app_data in self.chassis_software[
                    'applications'].items()
                if app_data['application_name'] == 'ftd' and str(
                app_data['slot']) == str(slot)]

    def define_dependent_states(self):
        all_apps = [app.get('application_identifier')
                    for slot in self.get_available_slots()
                    for app in self.get_available_ftds_on_slot(slot)]
        self.states_dependent_on_slot_and_app = []
        self.states_dependent_on_slot_only = []
        for state in self.states_dict:
            slot_dependent = False
            app_dependent = False
            app_name = ''
            if state.startswith('slot_'):
                slot_dependent = True
            for app in all_apps:
                if app in state:
                    app_name = app
                    app_dependent = True
            if slot_dependent and app_dependent:
                state_to_add = state.replace(
                    'slot_', '')[2:].replace(app_name + '_', '')
                if state_to_add not in self.states_dependent_on_slot_and_app:
                    self.states_dependent_on_slot_and_app.append(state_to_add)
            elif slot_dependent:
                state_to_add = state.replace('slot_', '')[2:]
                if state_to_add not in self.states_dependent_on_slot_only:
                    self.states_dependent_on_slot_only.append(state_to_add)

    def create(self):
        self.define_chassis_level_states()
        self.define_security_module_level_states()
        self.define_ftd_level_states()
        self.define_asa_level_states()
        self.add_states_to_state_machine()

        self.define_chassis_level_paths()
        self.define_ftd_level_paths()
        self.define_asa_level_paths()
        self.add_paths_to_state_machine()

        self.define_dependent_states()
        self.ftd_states = [self.states_dict[state] for state in self.states_dict
                           for name in ['fireos_state', 'expert_state',
                                        'sudo_state', 'enable_state',
                                        'disable_state', 'config_state']
                           if name in state]

        # after inactivity timer, it will go back to prelogin:
        self.add_default_statements(self.statements.login_password)

    def get_full_state_name(self, state_name):
        full_state_name = state_name
        if full_state_name in self.states_dependent_on_slot_only:
            if self.current_slot is None:
                raise RuntimeError(
                    'You need to set the current active slot'
                    'by calling set_current_slot(...) first.')
            full_state_name = 'slot_' + self.current_slot + '_' + full_state_name
        elif full_state_name in self.states_dependent_on_slot_and_app:
            if self.current_slot is None or \
                            self.current_application is None:
                raise RuntimeError(
                    'You need to set the current active slot'
                    'and current application identifier'
                    'by calling set_current_slot(...) and '
                    'set_current_application(...) first.')
            full_state_name = 'slot_' + self.current_slot + '_' + \
                       self.current_application + '_' + full_state_name
        return full_state_name

    def go_to(self, to_state, spawn,
              context=AttributeDict(),
              dialog=None,
              timeout=None,
              hop_wise=False,
              prompt_recovery=False):
        # get the composed full (slot_<slot>_<app>) state name
        to_state = self.get_full_state_name(to_state)

        # when a connection is made to the device and the device
        # is left in a random state we need to try to detect the
        # state or signal failure because going to 'any' state
        # can lead to circular transitions which go on in a loop
        # indefinetely
        if self.current_state == 'generic' and to_state is 'any':
            # try to detect in which state we are right now or fail
            # send a newline to initialize the prompt
            spawn.sendline('')
            # wait 10 seconds for the prompt to populate
            time.sleep(10)
            # match everything in the output buffer
            output = spawn.expect('.*', timeout=30).match_output
            for state_name, state_data in self.states_dict.items():
                pattern = state_data.pattern
                if isinstance(pattern, str):
                    if re.match(pattern, output.split('\r\n')[-1]):
                        self.update_cur_state(state_name)
                        return output
                if isinstance(pattern, list):
                    for pat in pattern:
                        if re.match(pat, output.split('\r\n')[-1]):
                            self.update_cur_state(state_name)
                            return output
            raise RuntimeError('Could not detect current state. Please ' +
                               'connect to the chassis and bring it to ' +
                               'the mio state prompt. Output is:' + output)
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

    def get_state(self, state_name):
        # get the composed full (slot_<slot>_<app>) state name
        state_name = self.get_full_state_name(state_name)
        return super().get_state(state_name)
