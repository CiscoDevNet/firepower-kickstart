import munch


class EpPatterns:
    """ Ep class for device prompt patterns
    """

    def __init__(self, hostname, login_username, login_password, sudo_password):
        """ Constructor for EpPatterns
        """
        self.hostname = hostname
        self.login_username = login_username
        self.login_password = login_password
        self.sudo_password = sudo_password
        self.prompt = munch.Munch()

        self.prompt.password_prompt = r'.*[Pp]assword.*: '
        self.prompt.prelogin_prompt = r'({} )login: '.format(self.hostname)
        self.prompt.admin_prompt = r'\r\n.*[a-zA-Z0-9.*]+@[a-zA-Z0-9.*].*[$]'
        self.prompt.sudo_prompt = r'\r\n.*[a-zA-Z0-9.*]+@[a-zA-Z0-9.*].*[#]'
