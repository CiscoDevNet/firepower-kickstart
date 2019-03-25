"""ASA prompt patterns."""
import munch


class AsaPatterns:
    def __init__(self, hostname, enable_password):
        self.enable_password = enable_password
        self.hostname = hostname

        self.prompt = munch.Munch()

        self.prompt.password_prompt = '[\r\n][Pp]assword: '
        self.prompt.set_enable_pwd_prompt = '[\r\n][Ee]nter +[Pp]assword: '
        self.prompt.repeat_enable_pwd_prompt = '[\r\n][Rr]epeat +[Pp]assword: '
        self.prompt.disable_prompt = '[\r\n]({}|ciscoasa|asa)[/\w\d\-]*> '.format(self.hostname)
        self.prompt.enable_prompt = '[\r\n]({}|ciscoasa|asa)[/\w\d\-]*# '.format(self.hostname)
        self.prompt.config_prompt = '[\r\n]({}|ciscoasa|asa)[/\w\d\-]*\([\w\-]+\)# '.format(self.hostname)

    def change_hostname(self, new_hostname):
        self.hostname = new_hostname
        self.prompt.disable_prompt = '[\r\n]({}|ciscoasa|asa)[/\w\d\-]*> '.format(self.hostname)
        self.prompt.enable_prompt = '[\r\n]({}|ciscoasa|asa)[/\w\d\-]*# '.format(self.hostname)
        self.prompt.config_prompt = '[\r\n]({}|ciscoasa|asa)[/\w\d\-]*\([\w\-]+\)# '.format(self.hostname)

    def change_enable_password(self, new_password):
        self.enable_password = new_password
