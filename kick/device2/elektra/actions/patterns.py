import munch


class ElektraPatterns:
    def __init__(self, hostname, login_password, sudo_password, enable_password):
        self.hostname = hostname
        self.username = 'admin'
        self.login_password = login_password
        self.sudo_password = sudo_password
        self.enable_password = enable_password
        self.default_password = 'Admin123'

        self.prompt = munch.Munch()

        self.prompt.password_prompt = '[\r\n][Pp]assword: '
        self.prompt.prelogin_prompt = '[\r\n]({} |firepower |asasfr |ciscoasa )login: '.format(self.hostname)
        self.prompt.fireos_prompt = r'[\r\n][\x07]?> $'
        self.prompt.expert_prompt = '[\r\n](admin@.*):~\$ $'
        self.prompt.sudo_prompt = '[\r\n](root@.*#) $'
        self.prompt.disable_prompt = '[\r\n]({}|firepower|ciscoasa)> $'.format(self.hostname)
        self.prompt.enable_prompt = '[\r\n]({}|firepower|ciscoasa)[/\w]*# $'.format(self.hostname)
        self.prompt.config_prompt = '[\r\n]({}|firepower|ciscoasa)[/\w]*\([\w\-]+\)# $'.format(self.hostname)
        self.prompt.rommon_prompt = 'rommon.*>'
        self.prompt.firepower_boot = '-boot>'
