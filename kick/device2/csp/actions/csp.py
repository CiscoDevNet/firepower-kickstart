try:
    from kick.graphite.graphite import publish_kick_metric
except ImportError:
    from kick.metrics.metrics import publish_kick_metric
from kick.device2.general.actions.basic import BasicDevice, BasicLine
from .patterns import CspPatterns
from .statemachine import CspStatemachine

DEFAULT_TIMEOUT = 30

class Csp(BasicDevice):
    """
    CSP Class
    """
    def __init__(self, hostname='csp'):
        """
        Initilize the CSP Instance
        :param hostname: Hostname of the csp 2100
        :param login_username: username for login
        :param login_password: password for login
        :return None

        """
        publish_kick_metric('device.csp.init', 1)
        self.patterns = CspPatterns(hostname)
        self.sm = CspStatemachine(self.patterns)

        self.line_class = CspLine
        super().__init__()


class CspLine(BasicLine):
    """
    CSP line class that provides interactive connection to the device
    """
    def __init__(self, spawn_id, sm, conn_type, timeout=None):
        """
        Initilizes the CSP Line
        :param spawn_id:
        :param sm: CSP StateMachine
        :param conn_type: telnet or ssh (connection type)
        :return None
        """
        if not timeout:
            timeout = DEFAULT_TIMEOUT

        super().__init__(spawn_id, sm, conn_type, timeout)

    def sudo_execute(self, cmd, timeout=None, exception_on_bad_command=False):
        """ Not implemented for CspLine class"""

        raise NotImplementedError

    def replace_asa_image(self, source_location, pwd, timeout=300):
        """ Not implemented for CspLine class"""

        raise NotImplementedError
