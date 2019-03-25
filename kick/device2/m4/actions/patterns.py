import munch


class M4Patterns:
    """FMC M4 class for device prompt patterns."""
    def __init__(self, hostname, cimc_hostname, login_username, login_password, sudo_password):
        """Constructor for M4Patterns."""

        self.fqdn = hostname
        self.hostname = hostname.split('.')[0]
        self.cimc_hostname = cimc_hostname
        self.login_username = login_username
        self.login_password = login_password
        self.sudo_password = sudo_password
        self.username = 'admin'
        self.default_password = 'Admin123'
        self.prompt = munch.Munch()

        self.prompt.password_prompt = r'.*[Pp]assword: '
        self.prompt.prelogin_prompt = r'\n?\r?({}([\w.]+)?|firepower) login: '.format(self.hostname)
        self.prompt.mio_prompt = r'{}([/\w\-\*\s]+)?# '.format(self.cimc_hostname)
        self.prompt.admin_prompt = r'\r\nadmin@({}|firepower).*$'.format(self.hostname)
        self.prompt.sudo_prompt = r'\r\nroot@({}|firepower).*#'.format(self.hostname)
        self.prompt.fireos_prompt = r'\r\n(\x1bE\x1b\[J)?[\x07]?> '

        self.prompt.lilo_boot_prompt = 'boot:'
        self.prompt.lilo_boot_menu_prompt = 'qqqqqqqqqqqqqqqqqqqqqqqqqqqqqq'
        self.prompt.lilo_os_prompt = "root@\(none\):.*#"
