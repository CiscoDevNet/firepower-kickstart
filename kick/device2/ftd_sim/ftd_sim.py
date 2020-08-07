import random
import time

import argparse


class FtdSim:
    def __init__(self, login_password, enable_password, ftd_hostname, random_disconnect=False):
        """
        Simulator for an ftd application.
        Can be used to test state transitions or other hard to reproduce
        bugs.
        :param login_password: the login password of the ftd
        :param enable_password: the enable password of the ftd
        """
        self.login_password = login_password
        self.enable_password = enable_password
        self.current_state = 'prelogin_state'
        self.current_prompt = ''
        self.random_disconnect = random_disconnect
        self.no_commands_processed = True
        self.ftd_hostname = ftd_hostname
        self.prelogin_state()

    def prelogin_state(self, command=''):
        """
        Simulates the prelogin state.
        :return: None
        """
        self.current_state = 'prelogin_state'
        self.current_prompt = 'Password: '
        while True:
            time.sleep(1)
            password = input(self.current_prompt)
            if password == self.login_password:
                print('Password OK')
                print()
                break
        self.fireos_state()

    def fireos_state(self, command=''):
        """
        Simulates the fireos state.
        :return: None
        """
        self.current_state = 'fireos_state'
        self.current_prompt = '> '
        if 'expert' in command:
            self.expert_state()
        elif 'system support diagnostic-cli' in command:
            self.disable_state()
        elif 'exit' in command:
            print('logout')
            self.prelogin_state()
        elif command == '':
            pass
        else:
            print(command + '_output_from_device')

    def expert_state(self, command=''):
        """
        Simulates the expert state.
        :return: None
        """
        self.current_state = 'expert_state'
        self.current_prompt = 'admin@{}:~$ '.format(self.ftd_hostname)
        if 'exit' in command:
            self.fireos_state()
        elif 'sudo su -' in command:
            self.sudo_state()
        elif 'sudo lina_cli' in command:
            self.disable_state()
        elif command == '':
            pass
        else:
            print(command + '_output_from_device')

    def sudo_state(self, command=''):
        """
        Simulates the sudo state.
        :return: None
        """
        self.current_state = 'sudo_state'
        self.current_prompt = 'root@{}:~# '.format(self.ftd_hostname)
        if 'exit' in command:
            self.expert_state()
        elif command == '':
            pass
        else:
            print(command + '_output_from_device')

    def enable_state(self, command=''):
        """
        Simulates the enable state.
        :return: None
        """
        self.current_state = 'enable_state'
        self.current_prompt = '{}# '.format(self.ftd_hostname)
        if 'disable' in command:
            self.disable_state()
        elif command == '':
            pass
        else:
            print(command + '_output_from_device')

    def disable_state(self, command=''):
        """
        Simulates the disable state.
        :return: None
        """
        self.current_state = 'disable_state'
        self.current_prompt = '{}> '.format(self.ftd_hostname)
        if 'en' in command:
            while True:
                password = input('Password: ')
                if password == self.enable_password:
                    self.enable_state()
                    break
                else:
                    print('Invalid password!')
        elif 'exit' in command:
            print('Console connection detached.')
            getattr(self, self.previous_state)()
        elif command == '':
            pass
        else:
            print(command + '_output_from_device')

    def process_disconnect(self, command):
        """
        Process disconnect command.
        """
        if not self.no_commands_processed:
            if self.random_disconnect:
                result = random.randint(1, 10)
                if result < 2:
                    command = '~.'
        if '~.' in command:
            print('Connection to ftd_sim closed.')
            time.sleep(1)
            exit(0)
        return command

    def process_states(self):
        """
        Processes commands like an ftd and interprets them accordingly.
        Commands can either take the device to a different state or if the
        command is not a state change command the command just gets echoed
        back to the prompt as a response.
        :return:
        """
        while True:
            command = input(self.current_prompt).strip()
            command = self.process_disconnect(command)
            state_handler = getattr(self, self.current_state)
            tmp_state = self.current_state
            state_handler(command)
            self.no_commands_processed = False
            if self.current_state == 'disable_state' and \
                    self.current_state != tmp_state and \
                    tmp_state != 'enable_state':
                self.previous_state = tmp_state


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--login_password', default='login_password')
    parser.add_argument('--enable_password', default='en_password')
    parser.add_argument('--random_disconnect', default=False)
    parser.add_argument('--ftd_hostname', default='firepower')
    args = parser.parse_args()

    ftd = FtdSim(args.login_password, args.enable_password, args.ftd_hostname,
                 bool(args.random_disconnect))
    ftd.process_states()
