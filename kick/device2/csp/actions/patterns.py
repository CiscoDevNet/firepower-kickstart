"""CSP prompt patterns."""
import munch


class CspPatterns:
    def __init__(self, hostname):
        """

        :param hostname: csp hostname
        :param port: port of the service
        """
        self.hostname = hostname
        self.prompt = munch.Munch()

        #csp Prompts
        self.prompt.enable_prompt = '[\r\n]({}|csp)[/\w]*# '.format(self.hostname)
        self.prompt.config_prompt = '[\r\n]({}|csp)[/\w]*\([\w\-]+\)# '.format(self.hostname)
