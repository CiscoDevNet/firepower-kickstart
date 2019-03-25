import munch


class Series3Patterns:
    """Series3 FTD class for device prompt patterns."""
    def __init__(self, hostname, login_username, login_password, sudo_password):
        """Constructor for Series3 Patterns."""

        self.hostname = hostname
        self.login_username = login_username
        self.login_password = login_password
        self.sudo_password = sudo_password
        self.username = 'admin'
        self.default_password = 'Admin123'
        self.prompt = munch.Munch()

        self.prompt.password_prompt = r'.*Password: '
        #self.prompt.prelogin_prompt = r'({} )login: '.format(self.hostname)
        self.prompt.prelogin_prompt = '\r?\n?({}|firepower) login: '.format(self.hostname)
        self.prompt.fireos_prompt = '\n[\x07]?>'
        self.prompt.expert_prompt = '\n(admin@{}*):~\$ '.format(self.hostname)
        self.prompt.sudo_prompt = r'\nroot@{}.*#'.format(self.hostname)
        self.prompt.eula_prompt = 'You must accept the EULA to continue'
        self.prompt.firstboot_prompt = 'You must change the password for '
        self.prompt.lilo_boot_prompt = 'boot:'
        self.prompt.lilo_boot_menu_prompt = 'qqqqqqqqqqqqqqqqqqqqqqqqqqqqqq'
        self.prompt.lilo_os_prompt = "root@\(none\):.*#"

