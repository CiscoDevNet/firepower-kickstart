import munch


class KpPatterns:
    """KP class that restores all prompt patterns."""
    def __init__(self, hostname, login_username, login_password, sudo_password, lina_hostname):
        self.hostname = hostname
        self.login_username = login_username
        self.login_password = login_password
        self.sudo_password = sudo_password
        self.default_password = 'Admin123'

        self.prompt = munch.Munch()

        self.prompt.password_prompt = r'.*[Pp]assword: '
        self.prompt.prelogin_prompt = r'[^\bLast \b](({}|firepower) )?login: '.format(self.hostname)

        # fxos related prompt
        self.prompt.fxos_prompt = r'({}|firepower)([ /\w\-\*\(\)]+)?# '.format(self.hostname)
        self.prompt.rommon_prompt = 'rommon.*>'
        self.prompt.local_mgmt_prompt = r'({}|firepower)\(local-mgmt\)# '.format(self.hostname)

        # ftd related prompt
        self.prompt.fireos_prompt = r'\r\n> $'
        self.prompt.expert_prompt = r'\r\n(\x1b.{{1,10}})?(admin@)?({}|firepower):.*?\$ $'.format(self.hostname)
        self.prompt.sudo_prompt = r'\r\nroot@.*# $'

        # lina_cli related propmpts
        self.prompt.disable_prompt = '[\r\n]{}> $'.format(lina_hostname)
        self.prompt.enable_prompt = '[\r\n]{}# $'.format(lina_hostname)
        self.prompt.config_prompt = '[\r\n]{}[\w]*\([\w\-]+\)# $'.format(lina_hostname)
