import munch


class Ftd5500xPatterns:
    def __init__(self, hostname, login_password, sudo_password, enable_password):
        self.hostname = hostname
        self.username = 'admin'
        self.login_password = login_password
        self.sudo_password = sudo_password
        self.enable_password = enable_password
        self.default_password = 'Admin123'

        self.prompt = munch.Munch()

        self.prompt.password_prompt = '\r\n[Pp]assword: $'
        self.prompt.prelogin_prompt = '\r?\n?({}|firepower|ciscoasa) login: $'.format(self.hostname)
        self.prompt.fireos_prompt = r'\r\n(\x1bE\x1b\[J)?[\x07]?> $'
        self.prompt.expert_prompt = r'\r\n(\x1b.{{1,10}})?(admin@)?({}|firepower):.*?\$ '.format(self.hostname)
        self.prompt.system_prompt = '\r\n[\x07]?system> $'
        self.prompt.sudo_prompt = '\r\n[^\r\n]*(root@.*#) ( \r|\r )*$'
        self.prompt.disable_prompt = '[\r\n]({}|firepower)> $'.format(self.hostname)
        self.prompt.enable_prompt = '[\r\n]({}|firepower)# $'.format(self.hostname)
        self.prompt.ciscoasa_prompt = '\r\nciscoasa:~\$'
        self.prompt.rommon_prompt = 'rommon.*> $'
        self.prompt.firepower_boot = '-boot>'
        self.prompt.config_prompt = '[\r\n]({}|firepower)[\w]*\([\w\-]+\)# $'.format(self.hostname)

