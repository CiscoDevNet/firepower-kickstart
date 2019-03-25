from .constants import WebserverConstants


class WebserverPatterns:
    password_prompt = '\n[Pp]assword: '
    user_prompt = '.*{}(:| ~\]).*\$ '.format(WebserverConstants.hostname)
