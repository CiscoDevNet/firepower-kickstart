"""patterns.py.

Chassis prompt patterns

"""
import munch


class ChassisPatterns:
    """SSP class that restores all prompt patterns."""
    def __init__(self, chassis_username, chassis_password,
                chassis_hostname, app_hostname):
        """Initializer of SspPatterns."""
        self.prompt = munch.Munch()
        self.chassis_username = chassis_username
        self.chassis_password = chassis_password
        self.chassis_hostname = chassis_hostname

        # the below 2 lines are for backward compatibility
        # should not be used internally in the library
        self.login_username = chassis_username
        self.login_password = chassis_password

        # Prelogin prompts
        self.prompt.password_prompt = r'[\r\n]*[Pp]assword: $'
        self.prompt.prelogin_prompt = \
            r'[\r\n]*({} )?([Ll]ast )?[Ll]ogin: $'.format(self.chassis_hostname)

        # MIO level prompts
        self.prompt.mio_prompt = r'[\r\n]*{}([ /\w\-\*\\]+)?# $'.format(self.chassis_hostname)
        self.prompt.local_mgmt_prompt = \
            r'[\r\n]*({})?\(local-mgmt\)# $'.format(self.chassis_hostname)
        self.prompt.fxos_prompt = r'[\r\n]*({})?\(fxos\)# $'.format(self.chassis_hostname)
        self.prompt.fpr_module_prompt = r'[\r\n]*Firepower-module.*>$'
        self.prompt.cimc_prompt = r'[\r\n]*\[.*?\]# $'

        # FTD level prompts
        self.prompt.fireos_prompt = r'[\r\n]*(\x1bE\x1b\[J)?> $'
        self.prompt.expert_cli = r'[\r\n]*(\x1b\[18t)?admin@.*?\$ $'
        self.prompt.sudo_prompt = r'[\r\n]*root@.*?# $'
        self.prompt.disable_prompt = '[\r\n]*({}|ftd\d*|firepower\d*|sensor\d*)> $'.format(app_hostname)
        self.prompt.enable_prompt = '[\r\n]*({}|ftd\d*|firepower\d*|sensor\d*)# $'.format(app_hostname)
        self.prompt.config_prompt = '[\r\n]*({}|ftd\d*|firepower\d*|sensor\d*)[\w]*\([\w\-]+\)# $'.format(
            app_hostname)

        # ASA level prompts
        self.prompt.asa_prompt = r'[\r\n]*asa.*?[>#] $'
