import munch


class Elektra5585Patterns:
    def __init__(self, hostname, login_password, sudo_password, enable_password):
        self.hostname = hostname
        self.username = 'admin'
        self.login_password = login_password
        self.sudo_password = sudo_password
        self.enable_password = enable_password
        self.default_password = 'Admin123'

        self.prompt = munch.Munch()

        self.prompt.password_prompt = '\r\n[Pp]assword: '
        self.prompt.prelogin_prompt = '\r?\n?({}|ciscoasa) login: '.format(self.hostname)
        self.prompt.pkglogin_prompt = '\r?\n?(SSP[1246]0SF|firepower|asasfr) login: '
        self.prompt.fireos_prompt = '\r\n[\x07]?> '
        self.prompt.system_prompt = '\r\n[\x07]?system> '
        self.prompt.expert_prompt = '\r\n[^\r\n]*admin@.*?\$ '
        self.prompt.sudo_prompt = '\r\n[^\r\n]*(root@.*#) '
        self.prompt.rommon_prompt = 'rommon.*>'
        self.prompt.firepower_boot = '-boot>'
        self.prompt.config_prompt = '[\r\n]({}|firepower)[\w]*\([\w\-]+\)# '.format(self.hostname)
