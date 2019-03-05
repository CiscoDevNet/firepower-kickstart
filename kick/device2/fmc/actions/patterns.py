import munch


class FmcPatterns:
    """ Fmc class for device prompt patterns
    """

    def __init__(self, hostname, login_username, login_password, sudo_password):
        """ Constructor for FmcPatterns
        """
        self.fqdn = hostname
        self.hostname = hostname.split('.')[0]
        self.login_username = login_username
        self.login_password = login_password
        self.sudo_password = sudo_password
        self.username = 'admin'
        self.default_password = 'Admin123'
        self.prompt = munch.Munch()

        self.prompt.password_prompt = r'.*[Pp]assword: '
        self.prompt.prelogin_prompt = r'(({}|firepower) )login: '.format(self.hostname)
        self.prompt.admin_prompt = r'\n{}@({}|firepower).*$'.format(self.login_username, self.hostname)
        self.prompt.sudo_prompt = r'\nroot@({}|firepower).*#'.format(self.hostname)
        self.prompt.fireos_prompt = r'\r\n(\x1bE\x1b\[J)?[\x07]?> '

        self.prompt.lilo_boot_prompt = 'boot:'
        self.prompt.lilo_boot_menu_prompt = 'qqqqqqqqqqqqqqqqqqqqqqqqqqqqqq'
        self.prompt.lilo_os_prompt = "root@\(none\):.*#"
